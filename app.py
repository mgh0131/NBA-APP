import streamlit as st
import pandas as pd
from nba_api.stats.endpoints import leaguestandings, scoreboardv2
from nba_api.stats.static import teams
from datetime import datetime
import pytz

# ==========================================
# 🔒 [비밀번호 설정]
# 여기 "7777"을 원하시는 비밀번호로 바꾸세요!
# ==========================================
MY_PASSWORD = st.secrets["password"] 

# --- 페이지 설정 ---
st.set_page_config(page_title="NBA AI 분석기", page_icon="🏀", layout="wide")

# --- 🔐 로그인 화면 로직 ---
# 비밀번호가 입력되지 않았거나 틀리면 여기서 멈춤
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.title("🔒 접속 제한구역")
    st.write("관계자 외 출입금지입니다.")
    
    password_input = st.text_input("비밀번호를 입력하세요:", type="password")
    
    if st.button("로그인"):
        if password_input == MY_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun() # 비밀번호 맞으면 새로고침해서 통과
        else:
            st.error("비밀번호가 틀렸습니다!")
    
    st.stop() # 비밀번호 통과 전까지 아래 코드 실행 안 함

# ==========================================
# 👇 여기서부터 원래 분석기 코드 시작
# ==========================================

st.title("🏀 NBA AI 승부사 (Mobile Ver.)")
st.caption(f"환영합니다! {datetime.now().strftime('%Y-%m-%d')} 데이터 분석 중...")

# --- 1. 데이터 로딩 함수 (캐싱 적용) ---
@st.cache_data(ttl=3600)
def load_nba_data():
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

        us_timezone = pytz.timezone("US/Eastern")
        today_us = datetime.now(us_timezone)
        board = scoreboardv2.ScoreboardV2(game_date=today_us.strftime('%m/%d/%Y'))
        games = board.game_header.get_data_frame()
        
        nba_teams = teams.get_teams()
        team_map = {team['id']: team['full_name'] for team in nba_teams}
        
        match_data = []
        for i, game in games.iterrows():
            home_id = game['HOME_TEAM_ID']
            away_id = game['VISITOR_TEAM_ID']
            h_name = team_map.get(home_id, "Unknown")
            a_name = team_map.get(away_id, "Unknown")
            
            hs = team_stats.get(home_id)
            as_ = team_stats.get(away_id)
            
            if hs and as_:
                match_data.append({
                    'home': eng_to_kor.get(h_name, h_name),
                    'away': eng_to_kor.get(a_name, a_name),
                    'hs': hs, 'as': as_
                })
        
        return match_data, today_us.strftime('%Y-%m-%d')

    except Exception as e:
        return None, str(e)

# --- 2. 메인 로직 ---
with st.spinner('데이터를 불러오는 중입니다...'):
    matches, date_str = load_nba_data()

if matches is None:
    st.error(f"데이터 로딩 실패: {date_str}")
else:
    st.success(f"✅ 경기 데이터 로드 완료 ({date_str} 기준)")
    st.markdown("---")
    
    input_data = []
    
    for idx, match in enumerate(matches):
        with st.expander(f"🏀 {match['home']} vs {match['away']}", expanded=True):
            col1, col2, col3 = st.columns(3)
            h_odd = col1.number_input("홈 배당", value=0.0, step=0.01, key=f"h_{idx}")
            a_odd = col2.number_input("원정 배당", value=0.0, step=0.01, key=f"a_{idx}")
            ref = col3.number_input("기준점", value=0.0, step=0.5, key=f"r_{idx}")
            
            input_data.append({'match': match, 'h_odd': h_odd, 'a_odd': a_odd, 'ref': ref})

    st.markdown("---")
    
    if st.button("🚀 분석 시작 (Click)", type="primary"):
        results = []
        
        for item in input_data:
            m = item['match']
            h_odd = item['h_odd']
            a_odd = item['a_odd']
            ref_score = item['ref']
            
            if h_odd == 0 or a_odd == 0: continue
            
            hs = m['hs']
            as_ = m['as']
            
            h_score = (hs['HomePCT']*0.4) + (hs['PointDiff']*0.03*0.3) + (hs['L10_PCT']*0.3)
            a_score = (as_['RoadPCT']*0.4) + (as_['PointDiff']*0.03*0.3) + (as_['L10_PCT']*0.3)
            
            if h_score < 0.05: h_score = 0.05
            if a_score < 0.05: a_score = 0.05
            
            total_power = h_score + a_score
            win_prob = h_score / total_power
            
            base_total = (hs['PointsPG'] + as_['OppPointsPG'])/2 + (as_['PointsPG'] + hs['OppPointsPG'])/2
            pace_adj = 0
            if base_total > 240: pace_adj = 3.0
            elif base_total < 215: pace_adj = -3.0
            ai_total = base_total + pace_adj
            
            h_ev = (win_prob * h_odd) - 1.0
            a_ev = ((1 - win_prob) * a_odd) - 1.0
            
            match_name = f"{m['home']} vs {m['away']}"
            
            if h_ev > 0 and h_ev > a_ev:
                results.append({'type': '승패', 'game': match_name, 'pick': f"{m['home']} 승", 'prob': win_prob*100, 'ev': h_ev, 'odd': h_odd})
            elif a_ev > 0 and a_ev > h_ev:
                results.append({'type': '승패', 'game': match_name, 'pick': f"{m['away']} 승 (역배/플핸)", 'prob': (1-win_prob)*100, 'ev': a_ev, 'odd': a_odd})
            
            if ref_score > 0:
                diff = ai_total - ref_score
                uo_odd = 1.90
                if diff >= 3.0:
                    prob = 55 + diff; prob = 80 if prob > 80 else prob
                    ev = (prob/100 * uo_odd) - 1.0
                    if ev > 0:
                         results.append({'type': '언오버', 'game': match_name, 'pick': f"오버 ▲ (기준 {ref_score})", 'prob': prob, 'ev': ev, 'odd': uo_odd})
                elif diff <= -3.0:
                    prob = 55 + abs(diff); prob = 80 if prob > 80 else prob
                    ev = (prob/100 * uo_odd) - 1.0
                    if ev > 0:
                        results.append({'type': '언오버', 'game': match_name, 'pick': f"언더 ▼ (기준 {ref_score})", 'prob': prob, 'ev': ev, 'odd': uo_odd})

        if not results:
            st.warning("⚠️ 추천할 만한 가치 있는 경기(Value Bet)가 없습니다.")
        else:
            results.sort(key=lambda x: x['ev'], reverse=True)
            
            st.subheader("🏆 AI 최종 추천 리포트")
            
            for i, res in enumerate(results):
                tier = "🌟 강력 추천" if i == 0 else "✅ 추천"
                
                with st.container():
                    st.markdown(f"#### {tier}: [{res['type']}] {res['game']}")
                    st.info(f"👉 **픽: {res['pick']}** (배당 {res['odd']})")
                    st.write(f"예상 확률: {res['prob']:.1f}% | 가치 점수: {res['ev']:.2f}")
                    st.markdown("---")

            if len(results) >= 2:
                st.success(f"💰 **2폴더 추천 조합:** {results[0]['pick']} + {results[1]['pick']} (총 배당 {(results[0]['odd']*results[1]['odd']):.2f}배)")
