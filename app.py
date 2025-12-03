import streamlit as st
import pandas as pd
from nba_api.stats.endpoints import leaguestandings, scoreboardv2, leaguegamelog
from nba_api.stats.static import teams
from datetime import datetime, timedelta
import pytz
import requests
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 🔒 [설정 로딩]
# ==========================================
try:
    MY_PASSWORD = st.secrets.get("password", "7777")
    ODDS_API_KEYS = st.secrets.get("odds_api_keys", [])
    if isinstance(ODDS_API_KEYS, str): ODDS_API_KEYS = [ODDS_API_KEYS]
    
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        SHEET_URL = st.secrets["connections"]["gsheets"]["spreadsheet"]
    elif "spreadsheet_url" in st.secrets:
        SHEET_URL = st.secrets["spreadsheet_url"]
    else:
        SHEET_URL = ""
except:
    MY_PASSWORD = "7777"
    ODDS_API_KEYS = []
    SHEET_URL = ""

MIN_BET = 10000   
MAX_BET = 100000 

# --- 페이지 설정 ---
st.set_page_config(page_title="도현&세준 NBA 프로젝트", page_icon="💸", layout="wide")

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
# 👇 메인 로직 시작
# ==========================================

st.markdown("### 💸 도현과 세준의 도박 프로젝트")
st.title("🏀 NBAI 7.0 (One-Touch Save)")

tab1, tab2 = st.tabs(["🚀 오늘의 분석", "📈 자산 대시보드 (가계부)"])

# -----------------------------------------------------------
# [기능] 구글 시트 연결
# -----------------------------------------------------------
conn = st.connection("gsheets", type=GSheetsConnection)

def get_ledger_data():
    if not SHEET_URL: return pd.DataFrame()
    try:
        # 캐시 끄고(ttl=0) 항상 최신 장부 가져오기
        df = conn.read(spreadsheet=SHEET_URL, ttl=0)
        if df.empty: return pd.DataFrame(columns=['날짜', '내용', '금액', '배당', '결과', '손익'])
        # 날짜 등 포맷 통일
        df['날짜'] = df['날짜'].astype(str)
        return df
    except:
        return pd.DataFrame(columns=['날짜', '내용', '금액', '배당', '결과', '손익'])

def add_ledger_entry(entry):
    if not SHEET_URL:
        st.error("구글 시트 주소 오류")
        return False
    try:
        df = get_ledger_data()
        # 입력된 데이터를 DataFrame으로 변환 (타입 강제)
        new_row = pd.DataFrame([entry])
        
        if df.empty: updated_df = new_row
        else: updated_df = pd.concat([df, new_row], ignore_index=True)
        
        conn.update(spreadsheet=SHEET_URL, data=updated_df)
        st.cache_data.clear() # 캐시 초기화
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

def update_ledger_data(updated_df):
    try:
        conn.update(spreadsheet=SHEET_URL, data=updated_df)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"수정 실패: {e}")
        return False

# -----------------------------------------------------------
# [기타 기능]
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
            try: return int(record.split('-')[0]) / (int(record.split('-')[0]) + int(record.split('-')[1]))
            except: return 0.5
        df['HomePCT'] = df['HOME'].apply(get_pct)
        df['RoadPCT'] = df['ROAD'].apply(get_pct)
        df['L10_PCT'] = df['L10'].apply(get_pct)
        team_stats = df.set_index('TeamID').to_dict('index')

        logs = []
        for s in ['2024-25', '2023-24']:
            try: logs.append(leaguegamelog.LeagueGameLog(season=s).get_data_frames()[0])
            except: pass
        total_log = pd.concat(logs) if logs else pd.DataFrame()
        return team_stats, total_log
    except: return None, None

def get_ai_prediction(home_id, away_id, team_stats, total_log):
    hs = team_stats.get(home_id); as_ = team_stats.get(away_id)
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
    if prob_score < 0.60: amount = max(amount * 0.4, MIN_BET)
    return round(amount, -3)

# -----------------------------------------------------------
# [탭 1] 오늘의 분석
# -----------------------------------------------------------
with tab1:
    st.caption("해외 배당 자동 로딩 + 천적 분석 + 자금 관리")
    
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
        
        odds_data = fetch_odds_with_rotation()
        odds_map = {}
        if odds_data:
            for game in odds_data:
                h_team = game['home_team']
                h_odd=0; a_odd=0; ref=0
                for book in game['bookmakers']:
                    for m in book['markets']:
                        if m['key']=='h2h':
                            for o in m['outcomes']:
                                if o['name']==h_team: h_odd=o['price']
                                else: a_odd=o['price']
                        if m['key']=='totals':
                            if m['outcomes']: ref=m['outcomes'][0]['point']
                odds_map[h_team] = {'h_odd':h_odd, 'a_odd':a_odd, 'ref':ref}

        match_data = []
        for i, game in games.iterrows():
            hid = game['HOME_TEAM_ID']; aid = game['VISITOR_TEAM_ID']
            h_eng = team_map.get(hid, "Unknown"); a_eng = team_map.get(aid, "Unknown")
            
            my_odds = {'h_odd':0.0, 'a_odd':0.0, 'ref':0.0}
            for k,v in odds_map.items():
                if h_eng in k or k in h_eng: my_odds=v; break
            
            win_prob, ai_total, h2h_factor = get_ai_prediction(hid, aid, team_stats, total_log)
            h2h_text = "상성 중립"
            if h2h_factor > 0: h2h_text = "🔥홈팀 천적 우세"
            elif h2h_factor < 0: h2h_text = "💀홈팀 상성 열세"
            
            match_data.append({
                'home': eng_to_kor.get(h_eng, h_eng), 'away': eng_to_kor.get(a_eng, a_eng),
                'prob': win_prob, 'total': ai_total, 'odds': my_odds,
                'h2h_text': h2h_text, 'h2h_factor': h2h_factor
            })
        return match_data, today_us.strftime('%Y-%m-%d')

    st.link_button("🇰🇷 실시간 부상자 확인 (네이버)", "https://m.sports.naver.com/basketball/schedule/index.nhn?category=nba")
    
    with st.expander("🏀 팀별 핵심 선수 명단 (족보)"):
        st.write("덴버:요키치, 미네소타:에드워즈, 오클라호마:SGA, 골스:커리, LAL:르브론/갈매기, 샌안:웸반야마")

    with st.spinner('서버 접속 중...'):
        matches, date_str = load_today_data()

    if matches is None:
        st.error("데이터 로딩 실패")
    else:
        st.success(f"✅ 분석 준비 완료 ({date_str})")
        input_data = []
        for idx, match in enumerate(matches):
            odds = match['odds']; badge = match['h2h_text'] if "상성" not in match['h2h_text'] else ""
            with st.expander(f"🏀 {match['home']} vs {match['away']} {badge}", expanded=True):
                c1, c2, c3 = st.columns(3)
                h_odd = c1.number_input(f"{match['home']} 승 배당", value=float(odds['h_odd']), step=0.01, key=f"h{idx}")
                a_odd = c2.number_input(f"{match['away']} 승 배당", value=float(odds['a_odd']), step=0.01, key=f"a{idx}")
                ref = c3.number_input("기준점", value=float(odds['ref']), step=0.5, key=f"r{idx}")
                input_data.append({'match': match, 'h_odd': h_odd, 'a_odd': a_odd, 'ref': ref})

        if st.button("🚀 NBAI 최종 분석 (Go)", type="primary"):
            results = []
            for item in input_data:
                m = item['match']; h_odd = item['h_odd']; a_odd = item['a_odd']; ref_score = item['ref']
                if h_odd == 0: continue
                win_prob = m['prob']; ai_total = m['total']
                h_ev = (win_prob*h_odd)-1; a_ev = ((1-win_prob)*a_odd)-1
                match_name = f"{m['home']} vs {m['away']}"
                note = f" | {m['h2h_text']}" if "천적" in m['h2h_text'] or "열세" in m['h2h_text'] else ""
                
                if h_ev > a_ev and h_ev > 0:
                    money = calc_money(h_ev, win_prob)
                    results.append({'type':'승패', 'game':match_name+note, 'pick':f"{m['home']} 승", 'odd':h_odd, 'ev':h_ev, 'prob':win_prob, 'money':money})
                elif a_ev > h_ev and a_ev > 0:
                    money = calc_money(a_ev, 1-win_prob)
                    results.append({'type':'승패', 'game':match_name+note, 'pick':f"{m['away']} 승", 'odd':a_odd, 'ev':a_ev, 'prob':1-win_prob, 'money':money})
                
                if ref_score > 0:
                    diff = ai_total - ref_score
                    if diff >= 3: results.append({'type':'언오버', 'game':match_name, 'pick':'오버', 'odd':1.9, 'ev':0.1, 'prob':0.6, 'money':calc_money(0.1, 0.6)})
                    elif diff <= -3: results.append({'type':'언오버', 'game':match_name, 'pick':'언더', 'odd':1.9, 'ev':0.1, 'prob':0.6, 'money':calc_money(0.1, 0.6)})

            if results:
                results.sort(key=lambda x: x['ev'], reverse=True)
                st.subheader("🏆 NBAI 추천 리포트")
                for r in results:
                    st.info(f"👉 {r['game']} : **{r['pick']}** (배당 {r['odd']})")
                
                if len(results) >= 2:
                    avg_score = (results[0]['prob'] + results[1]['prob']) / 2 * 100
                    ment = "✅ [안정] 꾸준한 수익 추천" if avg_score >= 70 else "🤔 [도전] 소액 추천"
                    if avg_score >= 80: ment = "🌟 [초강력] 풀매수 추천"
                    
                    final_money = (results[0]['money'] + results[1]['money']) / 2
                    final_money = round(final_money, -3)
                    
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
                    
                    # [핵심] 원터치 자동 저장 버튼
                    if st.button("📓 이 조합을 가계부에 바로 저장 (Click)", key="one_touch_save"):
                        with st.spinner("구글 시트에 기록 중..."):
                            entry = {
                                '날짜': datetime.now().strftime("%Y-%m-%d"),
                                '내용': f"{results[0]['pick']} + {results[1]['pick']}",
                                '금액': int(final_money),  # Python int형 강제
                                '배당': float(f"{total_odds:.2f}"), # Python float형 강제
                                '결과': '대기중',
                                '손익': 0
                            }
                            if add_ledger_entry(entry):
                                st.success("✅ 저장 완료! '가계부' 탭을 눌러 확인하세요.")
            else: st.warning("추천할 경기가 없습니다.")

# -----------------------------------------------------------
# [탭 2] 자산 대시보드 (가계부)
# -----------------------------------------------------------
with tab2:
    st.header("📈 자산 대시보드")
    
    df = get_ledger_data()
    
    if not df.empty:
        try:
            df['손익'] = pd.to_numeric(df['손익'])
            df['날짜'] = pd.to_datetime(df['날짜'])
            df = df.sort_values('날짜')
            
            total_profit = df['손익'].sum()
            win_count = len(df[df['결과'] == '적중'])
            total_count = len(df[df['결과'].isin(['적중', '미적중'])])
            win_rate = (win_count / total_count * 100) if total_count > 0 else 0
            
            c1, c2, c3 = st.columns(3)
            c1.metric("💰 누적 손익", f"{total_profit:,} 원", delta=f"{total_profit:,} 원")
            c2.metric("🎯 적중률", f"{win_rate:.1f}%", f"{win_count}/{total_count} 경기")
            c3.metric("📝 총 기록", f"{len(df)} 건")
            
            df['누적수익'] = df['손익'].cumsum()
            st.subheader("💸 내 자산 흐름 (우상향 체크)")
            st.line_chart(df.set_index('날짜')['누적수익'])
            
        except Exception as e:
            st.warning(f"통계 계산 오류: {e}")

        st.markdown("---")
        st.subheader("📋 상세 내역 (더블클릭하여 수정)")
        st.caption("결과를 '적중'이나 '미적중'으로 바꾸고 저장을 누르면 손익이 자동 계산됩니다.")
        
        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            key="ledger_editor",
            column_config={
                "결과": st.column_config.SelectboxColumn(
                    "결과",
                    options=["대기중", "적중", "미적중"],
                    required=True,
                )
            }
        )
        
        if st.button("💾 변경사항 저장 (수정/삭제 반영)"):
            edited_df['날짜'] = edited_df['날짜'].dt.strftime("%Y-%m-%d")
            
            # [중요] 손익 자동 재계산 로직
            def recalc_profit(row):
                try:
                    amt = float(str(row['금액']).replace(',', ''))
                    odd = float(row['배당'])
                    res = row['결과']
                    if res == "적중": return int((amt * odd) - amt)
                    elif res == "미적중": return int(-amt)
                    return 0
                except: return 0
            
            edited_df['손익'] = edited_df.apply(recalc_profit, axis=1)

            if '누적수익' in edited_df.columns:
                edited_df = edited_df.drop(columns=['누적수익'])
                
            if update_ledger_data(edited_df):
                st.success("완벽하게 저장되었습니다!")
                st.rerun()
                
    else:
        st.info("장부가 비어있습니다. '오늘의 분석' 탭에서 [장부에 담기]를 눌러보세요!")
