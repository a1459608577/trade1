# gui.py
# -*- coding: utf-8 -*-

import streamlit as st
import pandas as pd
import time
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


# ==========================================
# 🧠 逻辑继承与适配 (Adapter)
# ==========================================
# 我们继承原有的类，但重写 output 方法，让它返回 DataFrame 而不是打印文字
class StreamlitRadar(stock_radar.StockRadarPro):
    def get_raw_data(self, strategy_id, valid_boards):
        """
        获取原始数据，用于前端渲染
        """
        # 1. 设置策略
        stock_radar.CURRENT_STRATEGY = strategy_id

        # 2. 刷新数据
        if not self.zt_data:
            self._refresh_limit_pool()

        # 3. 获取热点板块
        concepts = self.scan_hot_concepts(top_n=3)

        results = {}  # {板块名: DataFrame}

        if concepts.empty:
            return None

        for _, row in concepts.iterrows():
            c_name = row.get('板块名称', '未知')
            c_pct = row['涨跌幅']

            # 获取成分股数据
            stock_list = self.get_concept_stocks_data(c_name, valid_boards)
            if stock_list:
                df = pd.DataFrame(stock_list)
                results[f"{c_name} ({c_pct}%)"] = df

        return results

    def get_concept_stocks_data(self, concept_name, valid_boards):
        """
        复用 deep_dive_concept 的逻辑，但只返回数据列表
        """
        try:
            # 1. 获取数据 (保持不变)
            df = pd.DataFrame()
            try:
                df = stock_radar.ak.stock_board_concept_cons_ths(symbol=concept_name)
            except:
                try:
                    df = stock_radar.ak.stock_board_concept_cons_em(symbol=concept_name)
                except:
                    pass

            if df.empty: return []

            # 2. 数据清洗 (保持不变)
            cols = ['涨跌幅', '现价', '最高', '最低', '换手', '量比']
            for col in cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # 排序：取前10名
            df_sorted = df.sort_values(by="涨跌幅", ascending=False).head(10)

            clean_data = []

            # 获取第一行的索引值，用于判断龙头 (比 enumerate 更准确)
            leader_index = df_sorted.index[0] if not df_sorted.empty else None

            for index, row in df_sorted.iterrows():
                code = str(row['代码'])
                name = row['名称']
                pct = row['涨跌幅']
                price = row.get('现价', 0)
                high = row.get('最高', price)
                low = row.get('最低', price)
                turnover = row.get('换手', 0)

                # 生成跳转链接 (建议所有股票都加链接)
                # 注意：这里需要确保 gui.py 里已经定义了 get_kline_url
                stock_url = get_kline_url(code)

                # 判定板块归属
                current_board = "主板 (60/00)"
                if code.startswith("30"):
                    current_board = "创业板 (300)"
                elif code.startswith("688"):
                    current_board = "科创板 (688)"
                elif code.startswith("8") or code.startswith("4"):
                    current_board = "北交所 (8/4)"

                # 判断是否有权限交易
                can_trade = current_board in valid_boards

                # 判定龙头逻辑：是否为排序后的第一名
                is_market_leader = (index == leader_index)

                # ============================================
                # 🛡️ 核心展示逻辑优化
                # ============================================

                # 【情况A】: 它是总龙头，但我买不了 -> 必须显示，作为“锚”
                if is_market_leader and not can_trade:
                    clean_data.append({
                        "代码": stock_url,  # 优化：即使买不了，加上链接方便点进去看行情
                        "名称": f"🔒 {name}",  # 加锁标记
                        "涨幅": f"{pct:.2f}%",
                        "现价": price,
                        "状态": "👑 总龙(锚)",  # 明确状态
                        "策略": "风向标",
                        "换手%": f"{turnover:.1f}"
                    })
                    continue  # 展示完直接跳过后续策略筛选

                # 【情况B】: 既不是龙头，我也买不了 -> 直接过滤，不看
                if not can_trade:
                    continue

                # 【情况C】: 我能买的股票 -> 进入常规筛选
                # (你原代码这里有一段重复的 if current_board not in valid_boards，已删除)

                if "ST" in name: continue

                threshold = self._get_limit_threshold(code, name)

                # 剔除一字板
                if self._is_one_word_board(high, low, pct, threshold):
                    continue

                # 策略筛选
                is_selected = True
                tag = "观察"

                # 调用 strategies.py
                if stock_radar.CURRENT_STRATEGY == 1:
                    is_selected, tag = StrategyFilter.check_strong_chase(row, threshold)
                elif stock_radar.CURRENT_STRATEGY == 2:
                    is_selected, tag = StrategyFilter.check_tail_end_lurk(row, threshold)
                elif stock_radar.CURRENT_STRATEGY == 3:
                    is_selected, tag = StrategyFilter.check_weak_to_strong(row, threshold)

                # 状态标记
                status = "普通"
                if code in self.zt_data:
                    streak = self.zt_data[code]
                    status = f"🔥 {streak}连板"
                elif code in self.zbgc_data:
                    status = "💣 炸板"
                elif pct > 8.0:
                    status = "⚡ 冲击"

                # 最终添加
                if is_selected or stock_radar.CURRENT_STRATEGY == 0:
                    clean_tag = tag.replace("🚀", "").replace("🐟", "").replace("⚡", "").strip()

                    clean_data.append({
                        "代码": stock_url,  # 已经是链接了
                        "名称": name,
                        "涨幅": f"{pct:.2f}%",
                        "现价": price,
                        "状态": status,
                        "策略": clean_tag,
                        "换手%": f"{turnover:.1f}"
                    })

            return clean_data

        except Exception as e:
            # st.error 可能会在非 GUI 线程报错，建议用 print 或直接 return
            print(f"数据解析错误: {e}")
            return []


# ==========================================
# 🖥️ 界面渲染 (UI Rendering)
# ==========================================

# 1. 侧边栏：控制台
with st.sidebar:
    st.header("🎮 操盘控制台")

    # 策略选择
    st_mode = st.radio(
        "选择战法模式:",
        (1, 2, 3, 0),
        format_func=lambda x: {
            1: "🚀 早盘强势追涨 (9:30-10:30)",
            2: "🐟 尾盘潜伏低吸 (14:30-15:00)",
            3: "⚡ 冲击涨停博弈 (激进)",
            0: "🔍 全市场热点扫描 (无过滤)"
        }[x]
    )

    st.markdown("---")
    st.markdown("🛠️ **交易权限设置**")

    # 多选框：默认全选
    selected_boards = st.multiselect(
        "只看我有权限买的板块:",
        options=["主板 (60/00)", "创业板 (300)", "科创板 (688)", "北交所 (8/4)"],
        default=["主板 (60/00)", "创业板 (300)", "科创板 (688)"],  # 默认不选北交所，因为太冷门
        help="取消勾选你无法交易的板块，选股器会自动过滤。"
    )

    # 手动刷新按钮
    if st.button("🔄 立即刷新数据", use_container_width=True):
        st.rerun()

    st.info("💡 提示：该界面每 60 秒会自动尝试刷新 (需手动开启循环或部署)")

# 2. 顶部：大盘情绪红绿灯
st.title("🚀 A股短线狙击雷达")
st.markdown("### 📊 市场情绪监控 (Market Sentiment)")

# 初始化
if 'radar' not in st.session_state:
    st.session_state.radar = StreamlitRadar()

# 获取情绪
with st.spinner('正在侦测大盘情绪...'):
    # 这里我们直接调用 sentiment.py，为了拿具体数值，建议你去修改 sentiment.py 返回字典
    # 这里为了演示，我们假设 check_mood 还是打印，我们只能重新简单算一下
    # 为了GUI好看，这里我们在GUI里简单复写一下获取数值的逻辑

    mood_data = MarketSentiment.check_mood(st.session_state.radar.today)
    # 注意：如果你还没修改 sentiment.py 返回字典，这里可能会报错。
    # 建议确保 sentiment.py 返回的是字典 {'level':.., 'sh_pct':.., 'premium':..}
    # 如果没改，这里用 try-except 兜底

    try:
        if isinstance(mood_data, int):  # 旧版只返回 int
            sh_pct = 0.0;
            premium = 0.0;
            level = mood_data
        else:
            sh_pct = mood_data.get('sh_pct', 0)
            premium = mood_data.get('premium', 0)
            level = mood_data.get('level', 0)
    except:
        sh_pct = 0;
        premium = 0;
        level = 0

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
        data_map = st.session_state.radar.get_raw_data(st_mode, selected_boards)

        if not data_map:
            st.warning("暂未获取到有效热点数据，可能是休市或接口波动。")
        else:
            # 遍历板块
            for bk_name, df in data_map.items():
                with st.expander(f"📂 {bk_name}", expanded=True):
                    if df.empty:
                        st.caption("该板块暂无符合当前策略的个股")
                    else:
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
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "代码": st.column_config.LinkColumn(
                                    "股票代码",
                                    help="点击跳转东方财富K线图",
                                    # 正则表达式：从URL中提取6位数字作为显示文本
                                    display_text=r"(\d{6})\.html",
                                    width="medium"
                                )
                            }
                        )

# 页脚
st.markdown("---")
st.caption(f"数据来源: 东方财富 & 同花顺 | 更新时间: {time.strftime('%H:%M:%S')}")