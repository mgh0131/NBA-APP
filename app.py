import streamlit as st
import pandas as pd
from nba_api.stats.endpoints import leaguestandings, scoreboardv2, leaguegamelog
from nba_api.stats.static import teams
from datetime import datetime, timedelta
import pytz
import requests

# ==========================================
# 🔒 [비밀번호 & API 키 & 자금 설정]
# ==========================================
try:
    MY_PASSWORD = st.secrets["password"]
    ODDS_API_KEY = st.secrets["odds_api_key"]
except:
    MY_PASSWORD = "7777"
    ODDS_API_KEY = "" 

# [사용자 설정] 배팅 한도 (단위: 원)
MIN_BET = 10000   # 최소 배팅금
MAX_BET = 100000  # 최대 배팅금

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

st.markdown("### 💸 도현과 세준의 도박 프로젝트")
st.title("🏀 NBAI 3.7.2 (Link Fix)")
st.caption("해외 배당 자동 로딩 + 천적 분석 + 자금 관리 + 어제 적중률 확인")

# -----------------------------------------------------------
# [공통 함수] 데이터 로딩 및 분석
# -----------------------------------------------------------
@st.cache_data(ttl=3600)
def load_nba_stats():
    try:
        # 1. 순위 데이터
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

        # 2. 맞대결(H2H) 로그
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

    # 상성 계산
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

    # 전력 분석
    h_power = (hs['HomePCT']*0.4) + (hs['PointDiff']*0.03*0.3) + (hs['L10_PCT']*0.3) + h2h_factor
    a_power = (as_['RoadPCT']*0.4) + (as_['PointDiff']*0.03*0.3) + (as_['L10_PCT']*0.3)
    
    if h_power < 0.05: h_power = 0.05
    if a_power < 0.05: a_power = 0.05
    win_prob = h_power / (h_power + a_power)
    
    ai_total = (hs['PointsPG'] + as_['OppPointsPG'])/2 + (as_['PointsPG'] + hs['OppPointsPG'])/2
    if ai_total > 240: ai_total += 3.0
    elif ai_total < 215: ai_total -= 3.0
    
    return win_prob, ai_total, h2h_factor

# -----------------------------------------------------------
# [메인] 오늘 경기 분석 함수
# -----------------------------------------------------------
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

    odds_map = {}
    if ODDS_API_KEY:
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

# -----------------------------------------------------------
# [신규] 어제 경기 결과 확인 함수
# -----------------------------------------------------------
def check_yesterday():
    team_stats, total_log = load_nba_stats()
    us_timezone = pytz.timezone("US/Eastern")
    yesterday = datetime.now(us_timezone) - timedelta(days=1)
    
    try:
        board = scoreboardv2.ScoreboardV2(game_date=yesterday.strftime('%m/%d/%Y'))
        games = board.game_header.get_data_frame()
        lines = board.line_score.get_data_frame()
        
        if games.empty: return None
        
        nba_teams = teams.get_teams()
        team_map = {team['id']: team['full_name'] for team in nba_teams}
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
        
        results = []
        for i, game in games.iterrows():
            game_id = game['GAME_ID']
            home_id = game['HOME_TEAM_ID']
            away_id = game['VISITOR_TEAM_ID']
            
            h_line = lines[(lines['GAME_ID'] == game_id) & (lines['TEAM_ID'] == home_id)]
            a_line = lines[(lines['GAME_ID'] == game_id) & (lines['TEAM_ID'] == away_id)]
            
            if h_line.empty or a_line.empty: continue
            
            h_score = h_line.iloc[0]['PTS']
            a_score = a_line.iloc[0]['PTS']
            real_winner = "Home" if h_score > a_score else "Away"
            
            win_prob, ai_total, _ = get_ai_prediction(home_id, away_id, team_stats, total_log)
            ai_pick = "Home" if win_prob > 0.5 else "Away"
            
            is_correct = (real_winner == ai_pick)
            
            h_name = team_map.get(home_id, "Home")
            a_name = team_map.get(away_id, "Away")
            
            results.append({
                'match': f"{eng_to_kor.get(h_name, h_name)} vs {eng_to_kor.get(a_name, a_name)}",
                'score': f"{int(h_score)} : {int(a_score)}",
                'ai_pick': f"{'홈승' if ai_pick=='Home' else '원정승'} ({win_prob*100:.0f}%)",
                'result': "✅ 적중" if is_correct else "❌ 미적중"
            })
            
        return results, yesterday.strftime('%m/%d')
        
    except: return None

# --- 화면 구성 ---
col1, col2 = st.columns([1, 1])
with col1:
    # [수정됨] 네이버 스포츠 일정 페이지로 연결 (확실한 주소)
    st.link_button("🇰🇷 실시간 부상자 확인 (네이버)", "https://m.sports.naver.com/basketball/schedule/nba")
with col2:
    if st.button("🔙 어제 경기 적중 확인"):
        with st.spinner("어제 경기 결과 채점 중..."):
            res_data, y_date = check_yesterday()
            if res_data:
                st.write(f"### 📅 {y_date} NBAI 성적표")
                hit_cnt = sum(1 for r in res_data if "✅" in r['result'])
                total_cnt = len(res_data)
                acc = (hit_cnt / total_cnt * 100) if total_cnt > 0 else 0
                
                st.info(f"총 {total_cnt}경기 중 **{hit_cnt}경기 적중** (승률 {acc:.1f}%)")
                
                df_res = pd.DataFrame(res_data)
                st.table(df_res[['match', 'score', 'ai_pick', 'result']])
            else:
                st.warning("어제 경기가 없거나 데이터를 불러올 수 없습니다.")

st.markdown("---")

# --- 메인 로직 실행 ---
with st.spinner('NBAI가 서버에 접속하여 전력+상성+자금을 분석 중입니다...'):
    matches, date_str = load_today_data()

if matches is None:
    st.error(f"데이터 로딩 실패: {date_str}")
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

    st.markdown("---")
    
    if st.button("🚀 NBAI 최종 분석 (Go)", type="primary"):
        results = []
        for item in input_data:
            m = item['match']; h_odd = item['h_odd']; a_odd = item['a_odd']; ref_score = item['ref']
            if h_odd == 0 or a_odd == 0: continue
            
            win_prob = m['prob']
            ai_total = m['total']
            
            # EV 계산
            h_ev = (win_prob * h_odd) - 1.0
            a_ev = ((1 - win_prob) * a_odd) - 1.0
            
            match_name = f"{m['home']} vs {m['away']}"
            note = f" | {m['h2h_text']}" if "천적" in m['h2h_text'] or "열세" in m['h2h_text'] else ""
            
            # 자금 관리 로직
            def calc_money(ev_score, prob_score):
                if ev_score <= 0: return 0
                ratio = min(ev_score / 0.20, 1.0)
                amount = MIN_BET + (MAX_BET - MIN_BET) * ratio
                if prob_score < 0.60:
                    amount = amount * 0.4
                    if amount < MIN_BET: amount = MIN_BET
                return round(amount, -3)

            if h_ev > 0 and h_ev > a_ev:
                bet_money = calc_money(h_ev, win_prob)
                results.append({'type': '승패', 'game': match_name + note, 'pick': f"{m['home']} 승", 'prob': win_prob*100, 'ev': h_ev, 'odd': h_odd, 'money': bet_money})
            elif a_ev > 0 and a_ev > h_ev:
                bet_money = calc_money(a_ev, 1-win_prob)
                results.append({'type': '승패', 'game': match_name + note, 'pick': f"{m['away']} 승 (역배/플핸)", 'prob': (1-win_prob)*100, 'ev': a_ev, 'odd': a_odd, 'money': bet_money})
            
            if ref_score > 0:
                diff = ai_total - ref_score
                uo_odd = 1.90
                if diff >= 3.0:
                    prob = 55 + diff; prob = 80 if prob > 80 else prob
                    ev = (prob/100 * uo_odd) - 1.0
                    if ev > 0: results.append({'type': '언오버', 'game': match_name, 'pick': f"오버 ▲ (기준 {ref_score})", 'prob': prob, 'ev': ev, 'odd': uo_odd, 'money': calc_money(ev*1.5, prob/100)})
                elif diff <= -3.0:
                    prob = 55 + abs(diff); prob = 80 if prob > 80 else prob
                    ev = (prob/100 * uo_odd) - 1.0
                    if ev > 0: results.append({'type': '언오버', 'game': match_name, 'pick': f"언더 ▼ (기준 {ref_score})", 'prob': prob, 'ev': ev, 'odd': uo_odd, 'money': calc_money(ev*1.5, prob/100)})

        if not results:
            st.warning("⚠️ 추천할 만한 가치 있는 경기(Value Bet)가 없습니다.")
        else:
            results.sort(key=lambda x: x['ev'], reverse=True)
            st.subheader("🏆 NBAI 최종 추천 리포트")
            for i, res in enumerate(results):
                tier = "🌟 강력 추천" if i == 0 else "✅ 추천"
                if res['money'] < MIN_BET: res['money'] = MIN_BET
                
                if "주의" in res['game']:
                    st.error(f"**{tier}**: {res['game']}\n\n👉 **{res['pick']}** (배당 {res['odd']})\n\n(확률 {res['prob']:.1f}% / 가치 {res['ev']:.2f})")
                else:
                    st.info(f"**{tier}**: {res['game']}\n\n👉 **{res['pick']}** (배당 {res['odd']})\n\n(확률 {res['prob']:.1f}% / 가치 {res['ev']:.2f})")
            
            if len(results) >= 2:
                avg_score = (results[0]['prob'] + results[1]['prob']) / 2
                
                if avg_score >= 80:
                    ment = "🌟 [초강력] 오늘 가장 확실한 조합입니다. 상한가(10만원) 근접 추천!"
                    base_money = 80000; max_money = 100000
                elif avg_score >= 70:
                    ment = "✅ [안정] 꾸준히 수익 내기 좋은 조합입니다."
                    base_money = 40000; max_money = 70000
                else:
                    ment = "🤔 [도전] 소액으로 고배당을 노려볼 만합니다."
                    base_money = 10000; max_money = 30000
                
                avg_ev = (results[0]['ev'] + results[1]['ev']) / 2
                ev_ratio = min(avg_ev / 0.2, 1.0) 
                final_money = base_money + (max_money - base_money) * ev_ratio
                final_money = round(final_money, -3)

                st.markdown("---")
                st.success(f"""
                💰 **[오늘의 2폴더 조합]**
                👉 **{results[0]['pick']}** + **{results[1]['pick']}**
                
                💸 **권장 배팅금: {int(final_money):,}원**
                💡 **AI 가이드:** {ment}
                """)
