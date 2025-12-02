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
    st.error("⚠️ Secrets에 'password'와 'odds_api_key'를 설정해주세요!")
    st.stop()

# --- 페이지 설정 ---
st.set_page_config(page_title="NBA AI 분석기", page_icon="🏀", layout="wide")

# --- 🔐 로그인 화면 ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.title("🔒 접속 제한구역")
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
st.title("🏀 NBA AI 승부사 (Auto Mode)")
st.caption("해외 배당 자동 로딩 중... (Bet365 기준)")

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
        try:
            url = f'https://api.the-odds-api.com/v4/sports/basketball_nba/odds/?regions=eu&markets=h2h,totals&apiKey={ODDS_API_KEY}'
            res = requests.get(url).json()
            
            # 배당 매핑 (팀 이름 매칭)
            for game in res:
                h_team = game['home_team']
                # 단순화된 매칭 로직
                h_key = h_team.replace("Los Angeles", "LA").replace("LA Clippers", "LA 클리퍼스") # 예외처리
                
                # 배당 추출 (Unibet, Bet365 등 평균)
                best_h_odd = 0
                best_a_odd = 0
                ref_point = 0
                
                for bookmaker in game['bookmakers']:
                    for market in bookmaker['markets']:
                        if market['key'] == 'h2h': # 승패
                            outcomes = market['outcomes']
                            for out in outcomes:
                                if out['name'] == game['home_team']: best_h_odd = out['price']
                                else: best_a_odd = out['price']
                        if market['key'] == 'totals': # 언오버
                            outcomes = market['outcomes']
                            if len(outcomes) > 0:
                                ref_point = outcomes[0]['point'] # 기준점
                
                # 매핑 키 저장 (영어 이름 앞글자 등 활용)
                odds_map[h_team] = {'h_odd': best_h_odd, 'a_odd': best_a_odd, 'ref': ref_point}
                
        except Exception as e:
            st.error(f"배당 로딩 실패: {e}")

        # C. 데이터 합치기
        match_data = []
        for i, game in games.iterrows():
            home_id = game['HOME_TEAM_ID']
            away_id = game['VISITOR_TEAM_ID']
            h_eng = team_map.get(home_id, "Unknown")
            a_eng = team_map.get(away_id, "Unknown")
            
            hs = team_stats.get(home_id)
            as_ = team_stats.get(away_id)
            
            # 배당 찾기 (이름 유사도 매칭)
            my_odds = {'h_odd': 0.0, 'a_odd': 0.0, 'ref': 0.0}
            for k, v in odds_map.items():
                if h_eng in k or k in h_eng: # 이름 포함되면 매칭
                    my_odds = v
                    break

            if hs and as_:
                match_data.append({
                    'home': eng_to_kor.get(h_eng, h_eng),
                    'away': eng_to_kor.get(a_eng, a_eng),
                    'hs': hs, 'as': as_,
                    'odds': my_odds
                })
        
        return match_data, today_us.strftime('%Y-%m-%d')

    except Exception as e:
        return None, str(e)

# --- 메인 로직 ---
with st.spinner('해외 배당 및 경기 데이터 로딩 중...'):
    matches, date_str = load_data_with_odds()

if matches is None:
    st.error(f"데이터 로딩 실패: {date_str}")
else:
    st.success(f"✅ 자동 입력 완료! ({date_str}) - 부족한 부분만 수정하세요.")
    st.markdown("---")
    
    input_data = []
    for idx, match in enumerate(matches):
        odds = match['odds']
        with st.expander(f"🏀 {match['home']} vs {match['away']}", expanded=True):
            col1, col2, col3 = st.columns(3)
            # 자동 입력값 적용
            h_odd = col1.number_input("홈 배당", value=float(odds['h_odd']), step=0.01, key=f"h_{idx}")
            a_odd = col2.number_input("원정 배당", value=float(odds['a_odd']), step=0.01, key=f"a_{idx}")
            ref = col3.number_input("기준점", value=float(odds['ref']), step=0.5, key=f"r_{idx}")
            input_data.append({'match': match, 'h_odd': h_odd, 'a_odd': a_odd, 'ref': ref})

    st.markdown("---")
    
    if st.button("🚀 분석 시작 (Click)", type="primary"):
        results = []
        for item in input_data:
            m = item['match']; h_odd = item['h_odd']; a_odd = item['a_odd']; ref_score = item['ref']
            if h_odd == 0 or a_odd == 0: continue
            
            hs = m['hs']; as_ = m['as']
            h_score = (hs['HomePCT']*0.4) + (hs['PointDiff']*0.03*0.3) + (hs['L10_PCT']*0.3)
            a_score = (as_['RoadPCT']*0.4) + (as_['PointDiff']*0.03*0.3) + (as_['L10_PCT']*0.3)
            if h_score < 0.05: h_score = 0.05
            if a_score < 0.05: a_score = 0.05
            total = h_score + a_score
            win_prob = h_score / total
            
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
                    if ev > 0: results.append({'type': '언오버', 'game': match_name, 'pick': f"오버 ▲ (기준 {ref_score})", 'prob': prob, 'ev': ev, 'odd': uo_odd})
                elif diff <= -3.0:
                    prob = 55 + abs(diff); prob = 80 if prob > 80 else prob
                    ev = (prob/100 * uo_odd) - 1.0
                    if ev > 0: results.append({'type': '언오버', 'game': match_name, 'pick': f"언더 ▼ (기준 {ref_score})", 'prob': prob, 'ev': ev, 'odd': uo_odd})

        if not results:
            st.warning("⚠️ 추천할 만한 가치 있는 경기(Value Bet)가 없습니다.")
        else:
            results.sort(key=lambda x: x['ev'], reverse=True)
            st.subheader("🏆 AI 최종 추천 리포트")
            for i, res in enumerate(results):
                tier = "🌟 강력 추천" if i == 0 else "✅ 추천"
                st.info(f"**{tier}**: {res['game']}\n\n👉 **{res['pick']}** (배당 {res['odd']})\n\n(확률 {res['prob']:.1f}% / 가치 {res['ev']:.2f})")
            
            if len(results) >= 2:
                avg_score = (results[0]['prob'] + results[1]['prob']) / 2
                if avg_score >= 80: ment = "🌟 [초강력 추천] 자신감 Max! 금액 태워도 좋습니다."
                elif avg_score >= 70: ment = "✅ [추천] 안정권입니다. 평소대로 가세요."
                else: ment = "🤔 [소액 도전] 리스크가 있습니다. 금액 조절하세요."
                
                st.markdown("---")
                st.success(f"""
                💰 **[오늘의 2폴더 조합]**
                👉 **{results[0]['pick']}** + **{results[1]['pick']}**
                📊 **AI 종합 확신 점수: {avg_score:.1f}점**
                💡 **AI 가이드:** {ment}
                💸 **총 배당: {(results[0]['odd']*results[1]['odd']):.2f}배**
                """)
