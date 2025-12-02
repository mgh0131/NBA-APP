import streamlit as st
import pandas as pd
from nba_api.stats.endpoints import leaguestandings, scoreboardv2
from nba_api.stats.static import teams
from datetime import datetime
import pytz
import requests

# ==========================================
# 🔒 [비밀번호 & API 키 설정]
# ==========================================
try:
    MY_PASSWORD = st.secrets["password"]
    ODDS_API_KEY = st.secrets["odds_api_key"]
except:
    # 혹시 키 설정 안 했을 때를 대비한 기본값 (설정하면 무시됨)
    MY_PASSWORD = "7777"
    ODDS_API_KEY = "" 

# --- 페이지 설정 ---
st.set_page_config(page_title="도현&세준 NBA 프로젝트", page_icon="💸", layout="wide")

# --- 🔐 로그인 화면 ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.title("🔒 접속 제한구역")
    st.write("관계자 외 출입금지")
    password_input = st.text_input("비밀번호 입력:", type="password")
    if st.button("로그인"):
        if password_input == MY_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다!")
    st.stop()

# ==========================================
# 👇 여기서부터 분석기 코드 시작
# ==========================================

# 🟢 [디자인 추가된 부분] 🟢
st.markdown("### 💸 도현과 세준의 도박 프로젝트") 
st.title("🏀 NBA AI 승부사 (Master Ver.)")
st.caption("해외 배당 자동 로딩 & AI 손익비 분석 시스템")

# --- 1. 데이터 로딩 함수 (배당 + 경기데이터) ---
@st.cache_data(ttl=3600)
def load_data_with_odds():
    # A. NBA 데이터 수집
    eng_to_kor = {
        'Atlanta Hawks': '애틀랜타', 'Boston Celtics': '보스턴', 'Brooklyn Nets': '브루클린',
        'Charlotte Hornets': '샬럿', 'Chicago Bulls': '시카고', 'Cleveland Cavaliers': '클리블랜드',
        'Dallas Mavericks': '댈러스', 'Denver Nuggets': '덴버', 'Detroit Pistons': '디트로이트',
        'Golden State Warriors': '골든스테이트', 'Houston Rockets': '휴스턴', 'Indiana Pacers': '인디애나',
        'Los Angeles Clippers': 'LA 클리퍼스', 'Los Angeles Lakers': 'LA 레이커스', 'Memphis Grizzlies': '멤피스',
        'Miami Heat': '마이애미', 'Milwaukee Bucks': '밀워키', 'Minnesota Timberwolves': '미네소타',
        'New Orleans Pelicans': '뉴올리언스', 'New York Knicks': '뉴욕', 'Oklahoma City Thunder': '오클라호마',
        'Orlando Magic': '올랜도', 'Philadelphia 76ers': '필라델피아', 'Phoenix Suns': '피닉스',
        'Portland Trail Blazers': '포틀랜드', 'Sacramento Kings': '새크라멘토', 'San Antonio Spurs': '샌안토니오',
        'Toronto Raptors': '토론토', 'Utah Jazz': '유타', 'Washington Wizards': '워싱턴'
    }

    try:
        # 1. 시즌 스탯
        try:
            standings = leaguestandings.LeagueStandings(season='2025-26')
            df = standings.get_data_frames()[0]
        except:
            standings = leaguestandings.LeagueStandings(season='2024-25')
            df = standings.get_data_frames()[0]

        if 'PointsPG' not in df.columns: df['PointsPG'] = 112.0
        if 'OppPointsPG' not in df.columns: df['OppPointsPG'] = 112.0
        df['PointDiff'] = df['PointsPG'] - df['OppPointsPG']
        
        def get_pct(record):
            try:
                w, l = map(int, record.split('-'))
                return w / (w + l) if (w + l) > 0 else 0.5
            except: return 0.5

        df['HomePCT'] = df['HOME'].apply(get_pct)
        df['RoadPCT'] = df['ROAD'].apply(get_pct)
        df['L10_PCT'] = df['L10'].apply(get_pct)
        team_stats = df.set_index('TeamID').to_dict('index')

        # 2. 오늘 경기 일정
        us_timezone = pytz.timezone("US/Eastern")
        today_us = datetime.now(us_timezone)
        board = scoreboardv2.ScoreboardV2(game_date=today_us.strftime('%m/%d/%Y'))
        games = board.game_header.get_data_frame()
        nba_teams = teams.get_teams()
        team_map = {team['id']: team['full_name'] for team in nba_teams}

        # B. 실시간 배당 API 호출
        odds_map = {}
        if ODDS_API_KEY: # 키가 있을 때만 실행
            try:
                url = f'https://api.the-odds-api.com/v4/sports/basketball_nba/odds/?regions=eu&markets=h2h,totals&apiKey={ODDS_API_KEY}'
                res = requests.get(url).json()
                
                for game in res:
                    h_team = game['home_team']
                    best_h_odd = 0; best_a_odd = 0; ref_point = 0
                    
                    for bookmaker in game['bookmakers']:
                        for market in bookmaker['markets']:
                            if market['key'] == 'h2h':
                                for out in market['outcomes']:
                                    if out['name'] == h_team: best_h_odd = out['price']
                                    else: best_a_odd = out['price']
                            if market['key'] == 'totals':
                                if len(market['outcomes']) > 0: ref_point = market['outcomes'][0]['point']
                    
                    odds_map[h_team] = {'h_odd': best_h_odd, 'a_odd': best_a_odd, 'ref': ref_point}
            except: pass

        # C. 데이터 합치기
        match_data = []
        for i, game in games.iterrows():
            home_id = game['HOME_TEAM_ID']
            away_id = game['VISITOR_TEAM_ID']
            h_eng = team_map.get(home_id, "Unknown")
            a_eng = team_map.get(away_id, "Unknown")
            
            hs = team_stats.get(home_id)
            as_ = team_stats.get(away_id)
            
            # 배당 찾기
