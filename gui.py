# gui.py
# -*- coding: utf-8 -*-

import streamlit as st
import pandas as pd
import time
import datetime
import os
import sqlite3
import stock_radar  # 引用你的主程序
from sentiment import MarketSentiment
from strategies import StrategyFilter
from colorama import Fore


# gui.py 顶部添加

def get_kline_url(code):
    """根据代码生成东方财富K线图链接"""
    prefix = "sz"  # 默认深圳 (00, 30开头)
    if code.startswith("6"):
        prefix = "sh"
    elif code.startswith("8") or code.startswith("4"):
        prefix = "bj"

    return f"https://quote.eastmoney.com/{prefix}{code}.html"


STRATEGY_LABELS = {
    1: "强势追涨",
    2: "尾盘潜伏",
    3: "冲击涨停",
    4: "趋势波段"
}


def _fmt_pct(value):
    if value is None:
        return "-"
    return f"{value:.2f}%"


def _fmt_num(value):
    if value is None:
        return "-"
    return f"{value:.2f}"


def _extract_strategy_ids(text, fallback_ids):
    if not text:
        return list(fallback_ids)
    ids = []
    for sid, label in STRATEGY_LABELS.items():
        if label in str(text):
            ids.append(sid)
    return ids if ids else list(fallback_ids)


def _evaluate_strategy_confirm(strategy_id, open_pct, volume_ratio, pullback_pct, above_pre_close):
    if above_pre_close is False:
        return "fail"

    conditions = []

    if strategy_id == 1:
        open_range = (-0.5, 3.5)
        volume_min = 1.2
        pullback_max = 1.8
        if open_pct is not None:
            conditions.append(open_range[0] <= open_pct <= open_range[1])
        if volume_ratio is not None and volume_ratio > 0:
            conditions.append(volume_ratio >= volume_min)
        if pullback_pct is not None:
            conditions.append(pullback_pct <= pullback_max)
    elif strategy_id == 2:
        open_range = (-1.0, 1.5)
        volume_range = (0.8, 2.0)
        pullback_max = 2.5
        if open_pct is not None:
            conditions.append(open_range[0] <= open_pct <= open_range[1])
        if volume_ratio is not None and volume_ratio > 0:
            conditions.append(volume_range[0] <= volume_ratio <= volume_range[1])
        if pullback_pct is not None:
            conditions.append(pullback_pct <= pullback_max)
    elif strategy_id == 3:
        open_range = (2.0, 6.0)
        volume_min = 1.4
        pullback_max = 1.2
        if open_pct is not None:
            conditions.append(open_range[0] <= open_pct <= open_range[1])
        if volume_ratio is not None and volume_ratio > 0:
            conditions.append(volume_ratio >= volume_min)
        if pullback_pct is not None:
            conditions.append(pullback_pct <= pullback_max)

    if above_pre_close is not None:
        conditions.append(above_pre_close)

    if not conditions:
        return "watch"

    passed = sum(1 for ok in conditions if ok)
    if passed == len(conditions):
        return "pass"
    if passed >= len(conditions) - 1:
        return "watch"
    return "fail"


def _aggregate_confirm_status(strategy_ids, open_pct, volume_ratio, pullback_pct, above_pre_close):
    status_map = {}
    for sid in strategy_ids:
        status_map[sid] = _evaluate_strategy_confirm(
            sid,
            open_pct,
            volume_ratio,
            pullback_pct,
            above_pre_close
        )

    if any(status == "pass" for status in status_map.values()):
        overall = "✅通过"
    elif any(status == "watch" for status in status_map.values()):
        overall = "🟡观察"
    else:
        overall = "❌放弃"

    detail_parts = []
    for sid in strategy_ids:
        label = STRATEGY_LABELS.get(sid, str(sid))
        status = status_map.get(sid, "watch")
        icon = "✅" if status == "pass" else ("🟡" if status == "watch" else "❌")
        detail_parts.append(f"{label}{icon}")

    return overall, " / ".join(detail_parts)


def _fetch_spot_for_codes(codes):
    if not codes:
        return pd.DataFrame()
    df = pd.DataFrame()
    try:
        df = stock_radar.ak.stock_zh_a_spot_em()
    except Exception:
        try:
            df = stock_radar.ak.stock_zh_a_spot()
        except Exception:
            return pd.DataFrame()
    if df.empty or "代码" not in df.columns:
        return pd.DataFrame()
    return df[df["代码"].astype(str).isin(codes)].copy()


def build_t1_confirmation(db_path, fallback_strategy_ids):
    if not os.path.exists(db_path):
        return pd.DataFrame(), "数据库不存在，无法生成次日确认。"

    conn = sqlite3.connect(db_path)
    try:
        candidates = pd.read_sql_query(
            """
            SELECT date, code, name, strategy, price, pct, timestamp
            FROM stock_candidates
            WHERE date = (SELECT MAX(date) FROM stock_candidates)
            ORDER BY timestamp DESC
            """,
            conn
        )
    finally:
        conn.close()

    if candidates.empty:
        return pd.DataFrame(), "暂无历史选股记录。"

    candidates = candidates.drop_duplicates(subset=["code"]).head(50)
    codes = candidates["code"].astype(str).tolist()

    spot_df = _fetch_spot_for_codes(codes)
    if spot_df.empty:
        return pd.DataFrame(), "未能获取实时行情数据。"

    for col in ["最新价", "今开", "昨收", "最高", "最低", "量比", "涨跌幅"]:
        if col in spot_df.columns:
            spot_df[col] = pd.to_numeric(spot_df[col], errors="coerce")

    spot_map = spot_df.set_index(spot_df["代码"].astype(str)).to_dict(orient="index")
    results = []

    for _, row in candidates.iterrows():
        code = str(row["code"])
        name = row["name"]
        strategy_text = row.get("strategy", "")
        spot = spot_map.get(code)

        if not spot:
            results.append({
                "代码": code,
                "名称": name,
                "策略": strategy_text,
                "开盘%": "-",
                "量比": "-",
                "回撤%": "-",
                "站上昨收": "-",
                "确认策略": "-",
                "结论": "❔无行情"
            })
            continue

        open_price = spot.get("今开")
        pre_close = spot.get("昨收")
        latest = spot.get("最新价")
        high = spot.get("最高")
        volume_ratio = spot.get("量比")

        open_pct = None
        if pre_close and pre_close > 0 and open_price:
            open_pct = (open_price - pre_close) / pre_close * 100

        pullback_pct = None
        if latest and latest > 0 and high:
            pullback_pct = (high - latest) / latest * 100

        above_pre_close = None
        if pre_close and pre_close > 0 and latest:
            above_pre_close = latest >= pre_close

        strategy_ids = _extract_strategy_ids(strategy_text, fallback_strategy_ids)
        overall_status, detail_status = _aggregate_confirm_status(
            strategy_ids,
            open_pct,
            volume_ratio,
            pullback_pct,
            above_pre_close
        )

        results.append({
            "代码": code,
            "名称": name,
            "策略": strategy_text,
            "开盘%": _fmt_pct(open_pct),
            "量比": _fmt_num(volume_ratio),
            "回撤%": _fmt_pct(pullback_pct),
            "站上昨收": "是" if above_pre_close else ("否" if above_pre_close is False else "-"),
            "确认策略": detail_status,
            "结论": overall_status
        })

    return pd.DataFrame(results), ""


# ==========================================
# 🎨 页面配置 (Page Config)
# ==========================================
st.set_page_config(
    page_title="🚀 A股短线狙击雷达",
    page_icon="📈",
    layout="wide",  # 宽屏模式，看数据更爽
    initial_sidebar_state="expanded"
)

# 注入自定义 CSS (让表格更紧凑，字体更好看)
st.markdown("""
<style>
    .stMetric {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 5px;
    }
    .stDataFrame { font-size: 12px; }
</style>
""", unsafe_allow_html=True)


# 定义缓存函数，TTL=180秒 (3分钟刷新一次足够了)
@st.cache_data(ttl=60)
def get_cached_raw_data(strategy_ids, valid_boards, _radar_instance):
    # 这里调用 radar 实例的方法
    return _radar_instance.get_raw_data(strategy_ids, valid_boards)


# ==========================================
# 🧠 逻辑继承与适配 (Adapter)
# ==========================================
# 我们继承原有的类，但重写 output 方法，让它返回 DataFrame 而不是打印文字
class StreamlitRadar(stock_radar.StockRadarPro):
    def get_raw_data(self, strategy_ids, valid_boards):
        """
        获取原始数据，用于前端渲染
        """
        # 1. 设置策略
        stock_radar.CURRENT_STRATEGY = strategy_ids

        # 2. 刷新数据
        if not self.zt_data:
            self._refresh_limit_pool()

        # 3. 获取热点板块
        concepts = self.scan_hot_concepts(top_n=3)

        results = {}  # {板块名: DataFrame}

        if concepts.empty:
            return None

        for _, row in concepts.iterrows():
            c_name = row.get('板块', row.get('板块名称', '未知'))
            c_pct = row['涨跌幅']

            # 获取成分股数据
            stock_list = self.get_concept_stocks_data(c_name, valid_boards)
            if stock_list:
                df = pd.DataFrame(stock_list)
                results[f"{c_name} ({c_pct}%)"] = df

        return results

    def get_concept_stocks_data(self, concept_name, valid_boards):
        """
        获取板块个股数据 (GUI版)
        """
        try:
            df = pd.DataFrame()

            # 🟢 1. 优先调用父类的东财获取方法
            if hasattr(self, '_fetch_em_stocks'):
                df = self._fetch_em_stocks(concept_name)

            # 🟡 2. 兜底逻辑
            if df.empty and hasattr(self, '_fetch_sina_concept_stocks'):
                df = self._fetch_sina_concept_stocks(concept_name)

            if df.empty: return []

            # --- 下面的逻辑保持不变 (数据清洗、排序、兜底展示) ---
            # 2. 数据清洗
            cols = ['涨跌幅', '现价', '最高', '最低', '换手', '量比']
            for col in cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # 排序：取前10名
            df_sorted = df.sort_values(by="涨跌幅", ascending=False).head(10)

            clean_data = []
            fallback_data = []

            leader_index = df_sorted.index[0] if not df_sorted.empty else None

            for index, row in df_sorted.iterrows():
                code = str(row['代码'])
                name = row['名称']
                pct = row['涨跌幅']
                price = row.get('现价', 0)
                high = row.get('最高', price)
                low = row.get('最低', price)
                turnover = row.get('换手', 0)

                stock_url = get_kline_url(code)

                # 判定板块归属
                current_board = "主板 (60/00)"
                if code.startswith("30"):
                    current_board = "创业板 (300)"
                elif code.startswith("688"):
                    current_board = "科创板 (688)"
                elif code.startswith("8") or code.startswith("4"):
                    current_board = "北交所 (8/4)"

                can_trade = current_board in valid_boards
                is_market_leader = (index == leader_index)

                if "ST" in name: continue
                threshold = self._get_limit_threshold(code, name)

                # 剔除一字板
                is_one_word = self._is_one_word_board(high, low, pct, threshold)

                # 策略筛选
                is_selected = True
                tag = "观察"
                strategy_ids = StrategyFilter.normalize_strategy_ids(stock_radar.CURRENT_STRATEGY)

                if strategy_ids:
                    is_selected, tag = StrategyFilter.apply_strategies(row, threshold, strategy_ids)

                # 状态标记
                status = "普通"
                if code in self.zt_data:
                    streak = self.zt_data[code]
                    status = f"🔥 {streak}连板"
                elif code in self.zbgc_data:
                    status = "💣 炸板"
                elif pct > 8.0:
                    status = "⚡ 冲击"

                # 构造基础数据项
                clean_tag = tag.replace("🚀", "").replace("🐟", "").replace("⚡", "").strip()
                item_data = {
                    "代码": stock_url,
                    "名称": name,
                    "涨幅": f"{pct:.2f}%",
                    "现价": price,
                    "状态": status,
                    "策略": tag.replace("🚀", "").replace("🐟", "").replace("⚡", "").strip(),
                    "换手%": f"{turnover:.1f}"
                }

                # --- 分流逻辑 ---

                # 1. 正常符合策略的 (且能交易、不是一字板)
                if is_selected and can_trade and not is_one_word:
                    clean_data.append(item_data)

                # 2. 收集前5名做兜底 (不管符不符合策略，只要能交易)
                if len(fallback_data) < 5:
                    fallback_item = item_data.copy()
                    # 如果这只票并不符合策略，强行改标签，方便前端识别
                    if not (is_selected and not is_one_word):
                        fallback_item['策略'] = "👀 板块前排"

                    # 标记不可交易的
                    if not can_trade:
                        fallback_item['名称'] = f"🔒 {name}"

                    fallback_data.append(fallback_item)

            # --- 最终返回 ---
            # 如果有策略选出的票，就返回策略票；否则返回兜底的前排票
            if clean_data:
                return clean_data
            else:
                return fallback_data

        except Exception as e:
            print(f"数据解析错误: {e}")
            return []


# ==========================================
# 🖥️ 界面渲染 (UI Rendering)
# ==========================================

# 初始化
if 'radar' not in st.session_state:
    st.session_state.radar = StreamlitRadar()

# 预先获取情绪，供侧边栏策略自动切换使用
with st.spinner('正在侦测大盘情绪...'):
    mood_data = MarketSentiment.check_mood(st.session_state.radar.today)

    try:
        if isinstance(mood_data, int):  # 旧版只返回 int
            sh_pct = 0.0
            premium = 0.0
            level = mood_data
        else:
            sh_pct = mood_data.get('sh_pct', 0)
            premium = mood_data.get('premium', 0)
            level = mood_data.get('level', 0)
    except:
        sh_pct = 0
        premium = 0
        level = 0

# 1. 侧边栏：控制台
# 1. 侧边栏：控制台
with st.sidebar:
    st.header("🎮 操盘控制台")

    if "auto_strategy" not in st.session_state:
        st.session_state.auto_strategy = True
    if "no_filter" not in st.session_state:
        st.session_state.no_filter = False
    if "selected_strategies" not in st.session_state:
        st.session_state.selected_strategies = [1, 2, 3]

    # --- 逻辑调整：先处理 Auto 策略的计算，这样表单提交后能正确计算出策略 ---
    # 注意：在 st.form 模式下，只有点击提交按钮触发 rerun 后，这里的 session_state 才会更新
    if st.session_state.auto_strategy and not st.session_state.no_filter:
        st.session_state.selected_strategies = stock_radar.resolve_strategy_ids(
            level,
            st.session_state.selected_strategies,
            auto_enabled=True
        )

    # === ✨ 修改开始：使用 st.form 包裹控件 ===
    with st.form(key='control_panel_form'):
        auto_strategy = st.checkbox("🧭 根据情绪自动切换策略", key="auto_strategy")
        no_filter = st.checkbox("🔍 全市场热点扫描 (无过滤)", key="no_filter")

        # 策略选择
        selected_strategies = st.multiselect(
            "选择战法模式(可多选):",
            options=[1, 2, 3, 4],
            format_func=lambda x: {
                1: "🚀 早盘强势追涨 (9:30-10:30)",
                2: "🐟 尾盘潜伏低吸 (14:30-15:00)",
                3: "⚡ 冲击涨停博弈 (激进)",
                4: "📈 趋势波段低吸 (稳健N型)"
            }[x],
            key="selected_strategies"
        )

        st.markdown("---")
        st.markdown("🛠️ **交易权限设置**")

        # 多选框：默认全选
        selected_boards = st.multiselect(
            "只看我有权限买的板块:",
            options=["主板 (60/00)", "创业板 (300)", "科创板 (688)", "北交所 (8/4)"],
            default=["主板 (60/00)", "创业板 (300)", "科创板 (688)"],  # 默认不选北交所
            help="取消勾选你无法交易的板块，选股器会自动过滤。"
        )

        st.markdown("<br>", unsafe_allow_html=True)  # 增加一点间距

        # 将原来的 st.button 改为 st.form_submit_button
        # 点击此按钮后，上述所有控件的状态才会提交给后台，并触发一次 Rerun
        refresh_btn = st.form_submit_button("🚀 执行扫描 / 刷新数据", use_container_width=True)
    # === ✨ 修改结束 ===

    st.info("💡 提示：调整上方选项后，请点击【执行扫描】按钮生效。")

# 2. 顶部：大盘情绪红绿灯
st.title("🚀 A股短线狙击雷达")
st.markdown("### 📊 市场情绪监控 (Market Sentiment)")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("上证指数涨幅", f"{sh_pct:.2f}%", delta_color="normal")
with col2:
    st.metric("昨日涨停溢价", f"{premium:.2f}%", delta_color="normal")
with col3:
    if level == 1:
        st.success("🟢 情绪高涨：大胆操作")
    elif level == -1:
        st.error("🔴 情绪冰点：建议空仓")
    else:
        st.warning("🟡 情绪震荡：控制仓位")

st.markdown("---")

# 3. 核心区域：热点板块展示
st.markdown("### 🔥 实时热点与龙头 (Hot Sectors)")

if level == -1:
    st.error("⛔ 触发熔断保护，停止扫描个股。请管住手！")
else:
    with st.spinner('正在扫描全市场数据...'):
        if no_filter:
            strategy_ids = []
        else:
            strategy_ids = stock_radar.resolve_strategy_ids(
                level,
                selected_strategies,
                auto_enabled=auto_strategy
            )
        data_map = get_cached_raw_data(strategy_ids, selected_boards, st.session_state.radar)

        if not data_map:
            st.warning("暂未获取到有效热点数据，可能是休市或接口波动。")
        else:
            # 遍历板块
            # 遍历板块
            for bk_name, df in data_map.items():
                with st.expander(f"📂 {bk_name}", expanded=True):
                    if df.empty:
                        st.caption("该板块暂无符合当前策略的个股")
                    else:
                        # === 🟢 新增逻辑：检测是否为兜底数据 ===
                        # 检查 '策略' 列是否包含 '板块前排' 这个关键词
                        is_fallback = False
                        if '策略' in df.columns:
                            is_fallback = df['策略'].astype(str).str.contains("板块前排").any()

                        if is_fallback:
                            st.warning("⚠️ 暂无符合【严格策略】的个股，以下为该板块【涨幅前 5】观察：")


                        # ======================================

                        # 高亮显示逻辑
                        def highlight_status(val):
                            color = ''
                            if '连板' in str(val):
                                color = 'background-color: #ffcccc'  # 浅红
                            elif '炸板' in str(val):
                                color = 'background-color: #ccffcc'  # 浅绿
                            return color


                        st.dataframe(
                            df.style.map(highlight_status, subset=['状态']),
                            width="stretch",  # <--- ✅ 新参数：拉伸填满
                            hide_index=True,
                            column_config={
                                "代码": st.column_config.LinkColumn(
                                    "股票代码",
                                    help="点击跳转东方财富K线图",
                                    display_text=r"(\d{6})\.html",
                                    width="medium"
                                )
                            }
                        )

# 4. 次日确认 (T+1 Check)
st.markdown("---")
st.markdown("### ✅ 选股验证 (最新记录)")

with st.spinner('正在生成次日确认...'):
    fallback_ids = selected_strategies if selected_strategies else [1, 2, 3]
    t1_df, t1_msg = build_t1_confirmation("stock_data.db", fallback_ids)
    if t1_msg:
        st.info(t1_msg)
    elif t1_df.empty:
        st.info("暂无可确认的股票。")
    else:
        st.dataframe(t1_df, width="stretch", hide_index=True)

# 页脚
st.markdown("---")
st.caption(f"数据来源: 东方财富 & 同花顺 | 更新时间: {time.strftime('%H:%M:%S')}")
