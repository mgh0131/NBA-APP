import streamlit as st
import pandas as pd
from nba_api.stats.endpoints import leaguestandings, scoreboardv2, leaguegamelog
from nba_api.stats.static import teams
from datetime import datetime, timedelta
import pytz
import requests

# ==========================================
# 🔒 [비밀번호 & 다중 키 로딩]
# ==========================================
try:
    MY_PASSWORD = st.secrets["password"]
    # 키 리스트 처리
    keys = st.secrets["odds_api_keys"]
    if isinstance(keys, str): ODDS_API_KEYS = [keys]
    else: ODDS_API_KEYS = keys
except:
    MY_PASSWORD = "7777"
    ODDS_API_KEYS = []

MIN_BET = 10000   
MAX_BET = 100000 

# --- 페이지 설정 ---
st.set_page_config(page_title="도현&세준 NBA 프로젝트", page_icon="💸", layout="wide")

# --- 🔐 로그인 ---
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
# 👇 메인 로직 시작
# ==========================================

st.markdown("### 💸 도현과 세준의 도박 프로젝트")
st.title("🏀 NBAI 4.2 (Auto Ledger)")

tab1, tab2 = st.tabs(["🚀 오늘의 분석", "📊 내 가계부 (자동/수동)"])

# -----------------------------------------------------------
# [기능] 키 자동 교체 (The Odds API)
# -----------------------------------------------------------
def fetch_odds_with_rotation():
    if not ODDS_API_KEYS: return None
    for key in ODDS_API_KEYS:
        try:
            url = f'https://api.the-odds-api.com/v4/sports/basketball_nba/odds/?regions=eu&markets=h2h,totals&apiKey={key}'
            res = requests.get(url)
            if res.status_code == 200: return res.json()
        except: continue
    return None

# -----------------------------------------------------------
# [기능] NBA 데이터 로딩
# -----------------------------------------------------------
@st.cache_data(ttl=3600)
def load_nba_stats():
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

        logs = []
        for s in ['2024-25', '2023-24']:
            try:
                l = leaguegamelog.LeagueGameLog(season=s).get_data_frames()[0]
                logs.append(l)
            except: pass
        total_log = pd.concat(logs) if logs else pd.DataFrame()
        
        return team_stats, total_log
    except:
        return None, None

def get_ai_prediction(home_id, away_id, team_stats, total_log):
    hs = team_stats.get(home_id)
    as_ = team_stats.get(away_id)
    if not hs or not as_: return 0.5, 0, 0

    h2h_factor = 0
    if not total_log.empty and 'TEAM_ID' in total_log.columns:
        h_games = total_log[total_log['TEAM_ID'] == home_id]['GAME_ID'].unique()
        a_games = total_log[total_log['TEAM_ID'] == away_id]['GAME_ID'].unique()
        matchups = list(set(h_games) & set(a_games))
        if len(matchups) > 0:
            h_wins = 0
            for g_id in matchups:
                row = total_log[(total_log['TEAM_ID'] == home_id) & (total_log['GAME_ID'] == g_id)]
                if not row.empty and row.iloc[0]['WL'] == 'W': h_wins += 1
            win_rate = h_wins / len(matchups)
            if win_rate >= 0.7: h2h_factor = 0.15
            elif win_rate <= 0.3: h2h_factor = -0.15

    h_power = (hs['HomePCT']*0.4) + (hs['PointDiff']*0.03*0.3) + (hs['L10_PCT']*0.3) + h2h_factor
    a_power = (as_['RoadPCT']*0.4) + (as_['PointDiff']*0.03*0.3) + (as_['L10_PCT']*0.3)
    
    if h_power < 0.05: h_power = 0.05
    if a_power < 0.05: a_power = 0.05
    win_prob = h_power / (h_power + a_power)
    
    ai_total = (hs['PointsPG'] + as_['OppPointsPG'])/2 + (as_['PointsPG'] + hs['OppPointsPG'])/2
    if ai_total > 240: ai_total += 3.0
    elif ai_total < 215: ai_total -= 3.0
    
    return win_prob, ai_total, h2h_factor

def calc_money(ev_score, prob_score):
    if ev_score <= 0: return 0
    ratio = min(ev_score / 0.20, 1.0)
    amount = MIN_BET + (MAX_BET - MIN_BET) * ratio
    if prob_score < 0.60:
        amount = amount * 0.4
        if amount < MIN_BET: amount = MIN_BET
    return round(amount, -3)

# -----------------------------------------------------------
# [탭 1] 오늘의 분석
# -----------------------------------------------------------
with tab1:
    st.caption("해외 배당 자동 로딩 (새로운 키 적용됨)")
    
    @st.cache_data(ttl=3600)
    def load_today_data():
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

        team_stats, total_log = load_nba_stats()
        if not team_stats: return None, "Stats Error"

        us_timezone = pytz.timezone("US/Eastern")
        today_us = datetime.now(us_timezone)
        board = scoreboardv2.ScoreboardV2(game_date=today_us.strftime('%m/%d/%Y'))
        games = board.game_header.get_data_frame()
        nba_teams = teams.get_teams()
        team_map = {team['id']: team['full_name'] for team in nba_teams}

        # 키 자동 교체 함수 사용
        odds_data = fetch_odds_with_rotation()
        odds_map = {}
        if odds_data:
            for game in odds_data:
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

        match_data = []
        for i, game in games.iterrows():
            home_id = game['HOME_TEAM_ID']
            away_id = game['VISITOR_TEAM_ID']
            h_eng = team_map.get(home_id, "Unknown")
            a_eng = team_map.get(away_id, "Unknown")
            
            my_odds = {'h_odd': 0.0, 'a_odd': 0.0, 'ref': 0.0}
            for k, v in odds_map.items():
                if h_eng in k or k in h_eng: my_odds = v; break

            win_prob, ai_total, h2h_factor = get_ai_prediction(home_id, away_id, team_stats, total_log)
            
            h2h_text = "상성 중립"
            if h2h_factor > 0: h2h_text = "🔥홈팀 천적 우세"
            elif h2h_factor < 0: h2h_text = "💀홈팀 상성 열세"

            match_data.append({
                'home': eng_to_kor.get(h_eng, h_eng),
                'away': eng_to_kor.get(a_eng, a_eng),
                'prob': win_prob, 'total': ai_total,
                'odds': my_odds, 'h2h_text': h2h_text, 'h2h_factor': h2h_factor
            })
        
        return match_data, today_us.strftime('%Y-%m-%d')

    # 화면 표시
    st.link_button("🇰🇷 실시간 부상자 확인 (네이버)", "https://m.sports.naver.com/basketball/schedule/index.nhn?category=nba")
    
    with st.expander("🏀 팀별 핵심 선수 명단 (족보)"):
        st.markdown("""
        | 서부 (West) | 👑 **1옵션 (핵심)** | ⚔️ **2옵션** |
        | :--- | :--- | :--- |
        | **덴버** | **요키치** 🚨 | 머레이 |
        | **미네소타** | **에드워즈** | 랜들 |
        | **오클라호마** | **S.알렉산더** 🚨 | 홈그렌 |
        | **골든스테이트** | **커리** 🚨 | 그린 |
        | **LAL** | **르브론** | A.데이비스 |
        | **샌안토니오** | **웸반야마** 🚨 | 크리스 폴 |
        """)

    with st.spinner('서버 접속 중...'):
        matches, date_str = load_today_data()

    if matches is None:
        st.error(f"데이터 로딩 실패")
    else:
        st.success(f"✅ 분석 준비 완료 ({date_str})")
        
        input_data = []
        for idx, match in enumerate(matches):
            odds = match['odds']
            rival_badge = ""
            if match['h2h_factor'] > 0: rival_badge = match['h2h_text']
            elif match['h2h_factor'] < 0: rival_badge = match['h2h_text']
                
            with st.expander(f"🏀 {match['home']} vs {match['away']} {rival_badge}", expanded=True):
                if rival_badge: st.caption(f"📊 {rival_badge}")
                col1, col2, col3 = st.columns(3)
                h_odd = col1.number_input("홈 배당", value=float(odds['h_odd']), step=0.01, key=f"h_{idx}")
                a_odd = col2.number_input("원정 배당", value=float(odds['a_odd']), step=0.01, key=f"a_{idx}")
                ref = col3.number_input("기준점", value=float(odds['ref']), step=0.5, key=f"r_{idx}")
                input_data.append({'match': match, 'h_odd': h_odd, 'a_odd': a_odd, 'ref': ref})

        if st.button("🚀 NBAI 최종 분석 (Go)", type="primary"):
            results = []
            for item in input_data:
                m = item['match']; h_odd = item['h_odd']; a_odd = item['a_odd']; ref_score = item['ref']
                if h_odd == 0 or a_odd == 0: continue
                
                win_prob = m['prob']
                ai_total = m['total']
                h_ev = (win_prob * h_odd) - 1.0
                a_ev = ((1 - win_prob) * a_odd) - 1.0
                match_name = f"{m['home']} vs {m['away']}"
                note = f" | {m['h2h_text']}" if "천적" in m['h2h_text'] or "열세" in m['h2h_text'] else ""

                if h_ev > 0 and h_ev > a_ev:
                    bet_money = calc_money(h_ev, win_prob)
                    results.append({'type': '승패', 'game': match_name + note, 'pick': f"{m['home']} 승", 'prob': win_prob*100, 'ev': h_ev, 'odd': h_odd, 'money': bet_money})
                elif a_ev > 0 and a_ev > h_ev:
                    bet_money = calc_money(a_ev, 1-win_prob)
                    results.append({'type': '승패', 'game': match_name + note, 'pick': f"{m['away']} 승 (역배/플핸)", 'prob': (1-win_prob)*100, 'ev': a_ev, 'odd': a_odd, 'money': bet_money})
                
                if ref_score > 0:
                    diff = ai_total - ref_score
                    uo_odd = 1.90
                    if diff >= 3.0: results.append({'type': '언오버', 'game': match_name, 'pick': f"오버 ▲ (기준 {ref_score})", 'prob': 60, 'ev': 0.1, 'odd': uo_odd, 'money': calc_money(0.1, 0.6)})
                    elif diff <= -3.0: results.append({'type': '언오버', 'game': match_name, 'pick': f"언더 ▼ (기준 {ref_score})", 'prob': 60, 'ev': 0.1, 'odd': uo_odd, 'money': calc_money(0.1, 0.6)})

            if results:
                results.sort(key=lambda x: x['ev'], reverse=True)
                st.subheader("🏆 NBAI 최종 추천 리포트")
                for i, res in enumerate(results):
                    tier = "🌟 강력 추천" if i == 0 else "✅ 추천"
                    if "주의" in res['game']: st.error(f"**{tier}**: {res['game']}\n\n👉 **{res['pick']}** (배당 {res['odd']})")
                    else: st.info(f"**{tier}**: {res['game']}\n\n👉 **{res['pick']}** (배당 {res['odd']})")
                
                if len(results) >= 2:
                    avg_score = (results[0]['prob'] + results[1]['prob']) / 2
                    if avg_score >= 80: ment = "🌟 [초강력] 오늘 가장 확실한 조합입니다. 상한가(10만원) 근접 추천!"
                    elif avg_score >= 70: ment = "✅ [안정] 꾸준히 수익 내기 좋은 조합입니다."
                    else: ment = "🤔 [도전] 소액으로 고배당을 노려볼 만합니다."
                    
                    base_money = 10000; max_money = 30000
                    if avg_score >= 70: base_money = 40000; max_money = 70000
                    if avg_score >= 80: base_money = 80000; max_money = 100000
                    
                    avg_ev = (results[0]['ev'] + results[1]['ev']) / 2
                    ev_ratio = min(avg_ev / 0.2, 1.0)
                    final_money = base_money + (max_money - base_money) * ev_ratio
                    final_money = round(final_money, -3)

                    st.markdown("---")
                    st.success(f"💰 **[오늘의 2폴더 조합]**\n\n👉 **{results[0]['pick']}** + **{results[1]['pick']}**\n\n💸 **권장 배팅금: {int(final_money):,}원**\n\n💡 **AI 가이드:** {ment}")
            else:
                st.warning("추천할 만한 경기가 없습니다.")

# -----------------------------------------------------------
# [탭 2] 내 가계부 (자동/수동 하이브리드)
# -----------------------------------------------------------
with tab2:
    st.header("📉 가계부 & 성적표")
    
    if 'ledger' not in st.session_state: st.session_state['ledger'] = []

    # 1. 자동 업데이트 버튼
    if st.button("🔄 최근 경기결과 자동 스캔 (어제/엊그제)"):
        with st.spinner("경기 결과 확인 중..."):
            team_stats, total_log = load_nba_stats()
            us_timezone = pytz.timezone("US/Eastern")
            
            # 최근 2일 조회
            for i in range(1, 3):
                d = datetime.now(us_timezone) - timedelta(days=i)
                d_str = d.strftime('%m/%d/%Y')
                
                try:
                    board = scoreboardv2.ScoreboardV2(game_date=d_str)
                    games = board.game_header.get_data_frame()
                    lines = board.line_score.get_data_frame()
                    if games.empty: continue
                    finished = games[games['GAME_STATUS_ID'] == 3] # 종료된 경기
                    
                    for _, game in finished.iterrows():
                        gid = game['GAME_ID']; hid = game['HOME_TEAM_ID']; aid = game['VISITOR_TEAM_ID']
                        h_pts = lines[(lines['GAME_ID']==gid) & (lines['TEAM_ID']==hid)].iloc[0]['PTS']
                        a_pts = lines[(lines['GAME_ID']==gid) & (lines['TEAM_ID']==aid)].iloc[0]['PTS']
                        
                        # AI 예측
                        win_prob, _, _ = get_ai_prediction(hid, aid, team_stats, total_log)
                        ai_pick = "홈승" if win_prob > 0.5 else "원정승"
                        winner = "홈승" if h_pts > a_pts else "원정승"
                        
                        # 가계부에 자동 추가 (중복 방지 로직은 생략, 사용자가 삭제 가능)
                        nba_teams = teams.get_teams()
                        t_map = {t['id']: t['full_name'] for t in nba_teams}
                        match_name = f"{t_map.get(hid)} vs {t_map.get(aid)}"
                        
                        # 결과 표시 (저장은 수동으로 유도하거나 여기서 자동 저장 가능)
                        st.info(f"[{d_str}] {match_name} | AI: {ai_pick} | 결과: {winner} ({'✅적중' if ai_pick==winner else '❌미적중'})")
                except: pass
            st.success("스캔 완료! 위 결과를 참고해서 아래에 기록하세요.")

    st.markdown("---")

    # 2. 수동 입력 폼
    st.subheader("✍️ 기록 입력하기")
    with st.form("ledger_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        date_in = c1.date_input("날짜", datetime.now())
        desc_in = c2.text_input("내용 (예: 골스 패배)", "골스 승")
        c3, c4, c5 = st.columns(3)
        amt_in = c3.number_input("금액", 0, 1000000, 30000, 1000)
        odd_in = c4.number_input("배당", 1.0, 10.0, 1.9, 0.1)
        res_in = c5.selectbox("결과", ["적중", "미적중"])
        
        if st.form_submit_button("💾 저장"):
            profit = (amt_in * odd_in) - amt_in if res_in == "적중" else -amt_in
            st.session_state['ledger'].append({
                '날짜': date_in.strftime("%Y-%m-%d"), '내용': desc_in,
                '금액': f"{amt_in:,}", '결과': res_in, '손익': profit
            })
            st.success("저장됨!")

    # 3. 장부 출력
    if st.session_state['ledger']:
        df = pd.DataFrame(st.session_state['ledger'])
        total = df['손익'].sum()
        color = "green" if total >= 0 else "red"
        st.markdown(f"### 💰 누적 손익: :{color}[{total:,} 원]")
        st.table(df)
        if st.button("초기화"):
            st.session_state['ledger'] = []
            st.rerun()
