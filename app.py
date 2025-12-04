import streamlit as st
import pandas as pd
from nba_api.stats.endpoints import leaguestandings, scoreboardv2, leaguegamelog
from nba_api.stats.static import teams
from datetime import datetime, timedelta
import pytz
import requests

# ==========================================
# 🔒 [설정 로딩]
# ==========================================
try:
    MY_PASSWORD = st.secrets.get("password", "7777")
    ODDS_API_KEYS = st.secrets.get("odds_api_keys", [])
    if isinstance(ODDS_API_KEYS, str): ODDS_API_KEYS = [ODDS_API_KEYS]
except:
    MY_PASSWORD = "7777"
    ODDS_API_KEYS = []

MIN_BET = 10000   
MAX_BET = 100000 

# --- 페이지 설정 ---
st.set_page_config(page_title="도현&세준 NBA 프로젝트", page_icon="🏀", layout="wide")

# --- 🔐 로그인 ---
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
# 👇 메인 로직 (분석 전용)
# ==========================================

st.markdown("### 💸 도현과 세준의 도박 프로젝트")
st.title("🏀 NBAI Final (Pure Analysis)")
st.caption("오직 승리를 위한 데이터 분석에만 집중합니다.")

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
# [기능] NBA 데이터 로딩 & 분석
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

        # 상성 분석용 로그 (최근 2년)
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

    # 천적(상성) 계산
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

    # 전력 점수 계산
    h_power = (hs['HomePCT']*0.4) + (hs['PointDiff']*0.03*0.3) + (hs['L10_PCT']*0.3) + h2h_factor
    a_power = (as_['RoadPCT']*0.4) + (as_['PointDiff']*0.03*0.3) + (as_['L10_PCT']*0.3)
    
    if h_power < 0.05: h_power = 0.05
    if a_power < 0.05: a_power = 0.05
    win_prob = h_power / (h_power + a_power)
    
    # 예상 득점
    ai_total = (hs['PointsPG'] + as_['OppPointsPG'])/2 + (as_['PointsPG'] + hs['OppPointsPG'])/2
    if ai_total > 240: ai_total += 3.0
    elif ai_total < 215: ai_total -= 3.0
    
    return win_prob, ai_total, h2h_factor

def calc_money(ev_score, prob_score):
    if ev_score <= 0: return 0
    ratio = min(ev_score / 0.20, 1.0)
    amount = MIN_BET + (MAX_BET - MIN_BET) * ratio
    # 확신도가 낮으면 금액 강제 하향 (안전장치)
    if prob_score < 0.60:
        amount = amount * 0.4
        if amount < MIN_BET: amount = MIN_BET
    return round(amount, -3)

# -----------------------------------------------------------
# [메인 화면 구성]
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

    # 배당 API 호출 (키 교체 로직 포함)
    odds_data = fetch_odds_with_rotation()
    odds_map = {}
    if odds_data:
        for game in odds_data:
            h_team = game['home_team']
            h_odd = 0; a_odd = 0; ref = 0
            for book in game['bookmakers']:
                for m in book['markets']:
                    if m['key'] == 'h2h':
                        for o in m['outcomes']:
                            if o['name'] == h_team: h_odd = o['price']
                            else: a_odd = o['price']
                    if m['key'] == 'totals':
                        if m['outcomes']: ref = m['outcomes'][0]['point']
            odds_map[h_team] = {'h_odd': h_odd, 'a_odd': a_odd, 'ref': ref}

    match_data = []
    for i, game in games.iterrows():
        home_id = game['HOME_TEAM_ID']
        away_id = game['VISITOR_TEAM_ID']
        h_eng = team_map.get(home_id, "Unknown")
        a_eng = team_map.get(away_id, "Unknown")
        
        # 배당 매핑
        my_odds = {'h_odd': 0.0, 'a_odd': 0.0, 'ref': 0.0}
        for k, v in odds_map.items():
            if h_eng in k or k in h_eng: my_odds = v; break

        # AI 분석 실행
        win_prob, ai_total, h2h_factor = get_ai_prediction(home_id, away_id, team_stats, total_log)
        
        h2h_text = "상성 중립"
        if h2h_factor > 0: h2h_text = "🔥홈팀 천적 우세"
        elif h2h_factor < 0: h2h_text = "💀홈팀 상성 열세"

        match_data.append({
            'home': eng_to_kor.get(h_eng, h_eng),
            'away': eng_to_kor.get(a_eng, a_eng),
            'prob': win_prob, 'total': ai_total,
            'odds': my_odds, 'h2h_text': h2h_text
        })
    
    return match_data, today_us.strftime('%Y-%m-%d')

# -----------------------
# 화면 표시
# -----------------------
# 1. 부상자 확인 링크 (네이버 직통)
st.link_button("🇰🇷 실시간 부상자 확인 (네이버)", "https://m.sports.naver.com/basketball/schedule/index.nhn?category=nba")

# 2. 핵심 선수 족보
with st.expander("🏀 팀별 핵심 선수 명단 (족보)"):
    st.markdown("""
    | 서부 (West) | 👑 **1옵션 (핵심)** | ⚔️ **2옵션** |
    | :--- | :--- | :--- |
    | **덴버** | **요키치 (Jokic)** 🚨 | 머레이 |
    | **미네소타** | **에드워즈 (Edwards)** | 랜들/고베어 |
    | **오클라호마** | **S.알렉산더 (SGA)** 🚨 | 홈그렌 |
    | **골든스테이트** | **커리 (Curry)** 🚨 | 그린 |
    | **LA 레이커스** | **르브론 (LeBron)** | A.데이비스 |
    | **피닉스** | **듀란트 (Durant)** | 부커 |
    | **댈러스** | **돈치치 (Doncic)** 🚨 | 어빙 |
    | **멤피스** | **모란트 (Morant)** 🚨 | JJJ |
    | **샌안토니오** | **웸반야마 (Wemby)** 🚨 | 크리스 폴 |

    | 동부 (East) | 👑 **1옵션 (핵심)** | ⚔️ **2옵션** |
    | :--- | :--- | :--- |
    | **보스턴** | **테이텀 (Tatum)** 🚨 | 브라운 |
    | **뉴욕** | **브런슨 (Brunson)** 🚨 | 타운스 |
    | **필라델피아** | **엠비드 (Embiid)** 🚨 | 조지/맥시 |
    | **밀워키** | **아데토쿤보 (Giannis)** 🚨 | 릴라드 |
    | **클리블랜드** | **미첼 (Mitchell)** | 갈란드 |
    | **인디애나** | **할리버튼 (Hali)** 🚨 | 시아캄 |
    | **애틀랜타** | **트레이 영 (Young)** | J.존슨 |
    | **마이애미** | **버틀러 (Butler)** | 아데바요 |
    """)

st.markdown("---")

with st.spinner('NBAI가 서버에 접속하여 전력을 분석 중입니다...'):
    matches, date_str = load_today_data()

if matches is None:
    st.error("데이터 로딩 실패: 잠시 후 다시 시도하거나 수동 분석을 이용하세요.")
else:
    st.success(f"✅ 분석 준비 완료 ({date_str})")
    
    input_data = []
    for idx, match in enumerate(matches):
        odds = match['odds']
        rival_badge = ""
        # 상성이 있을 때만 뱃지 표시
        if "천적" in match['h2h_text'] or "열세" in match['h2h_text']:
            rival_badge = match['h2h_text']
            
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
            
            # 승패 추천
            if h_ev > 0 and h_ev > a_ev:
                bet_money = calc_money(h_ev, win_prob)
                results.append({'type':'승패', 'game':match_name+note, 'pick':f"{m['home']} 승", 'prob':win_prob*100, 'ev':h_ev, 'odd':h_odd, 'money':bet_money})
            elif a_ev > 0 and a_ev > h_ev:
                bet_money = calc_money(a_ev, 1-win_prob)
                results.append({'type':'승패', 'game':match_name+note, 'pick':f"{m['away']} 승 (역배/플핸)", 'prob':(1-win_prob)*100, 'ev':a_ev, 'odd':a_odd, 'money':bet_money})
            
            # 언오버 추천
            if ref_score > 0:
                diff = ai_total - ref_score
                uo_odd = 1.90
                if diff >= 3.0:
                    prob = 60; money = calc_money(0.1, 0.6)
                    results.append({'type':'언오버', 'game':match_name, 'pick':f"오버 ▲ (기준 {ref_score})", 'prob':prob, 'ev':0.1, 'odd':uo_odd, 'money':money})
                elif diff <= -3.0:
                    prob = 60; money = calc_money(0.1, 0.6)
                    results.append({'type':'언오버', 'game':match_name, 'pick':f"언더 ▼ (기준 {ref_score})", 'prob':prob, 'ev':0.1, 'odd':uo_odd, 'money':money})

        if not results:
            st.warning("⚠️ 추천할 만한 가치 있는 경기(Value Bet)가 없습니다.")
        else:
            results.sort(key=lambda x: x['ev'], reverse=True)
            st.subheader("🏆 NBAI 최종 추천 리포트")
            
            for i, res in enumerate(results):
                tier = "🌟 강력 추천" if i == 0 else "✅ 추천"
                if "주의" in res['game']:
                    st.error(f"**{tier}**: {res['game']}\n\n👉 **{res['pick']}** (배당 {res['odd']})")
                else:
                    st.info(f"**{tier}**: {res['game']}\n\n👉 **{res['pick']}** (배당 {res['odd']})")
            
            if len(results) >= 2:
                avg_score = (results[0]['prob'] + results[1]['prob']) / 2
                
                # 금액 구간 고정
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
                
                # 예상 당첨금
                total_odds = results[0]['odd'] * results[1]['odd']
                expected_return = final_money * total_odds

                st.markdown("---")
                st.success(f"""
                💰 **[오늘의 2폴더 조합]**
                👉 **{results[0]['pick']}** + **{results[1]['pick']}**
                
                💸 **권장 배팅금: {int(final_money):,}원**
                💵 **예상 당첨금: {int(expected_return):,}원** (총 배당 {total_odds:.2f}배)
                💡 **AI 가이드:** {ment}
                """)
