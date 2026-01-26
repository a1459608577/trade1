# stock_radar.py
# -*- coding: utf-8 -*-

import akshare as ak
import pandas as pd
import datetime
import time
import sys # 记得加这个，如果strategies里没用到sys可以不加，但这里如果要退出可能需要
from colorama import init, Fore, Style
from colorama import init, Fore, Style
from strategies import StrategyFilter  # <--- 引用刚才的文件
from sentiment import MarketSentiment
from db_manager import DBManager

init(autoreset=True)
pd.set_option('display.max_columns', None)
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)

# ==========================================
# ⚙️ 策略配置 (修改这里来切换玩法)
# 1 = 早盘强势 (9:30-10:30)
# 2 = 尾盘潜伏 (14:30-15:00)
# 3 = 冲击涨停 (激进)
# 0 = 不筛选 (显示板块内所有大涨股)
# 也可使用列表，如 [1, 2, 3] 同时启用多种风格
# ==========================================
CURRENT_STRATEGY = 2
AUTO_STRATEGY = True
AUTO_STRATEGY_MAP = {
    1: [1, 3],
    0: [2],
    -1: []
}


def resolve_strategy_ids(mood_level, manual_strategy, auto_enabled=None, auto_map=None):
    if auto_enabled is None:
        auto_enabled = AUTO_STRATEGY
    if auto_map is None:
        auto_map = AUTO_STRATEGY_MAP
    if auto_enabled:
        return StrategyFilter.normalize_strategy_ids(auto_map.get(mood_level, []))
    return StrategyFilter.normalize_strategy_ids(manual_strategy)


# ==========================================

class StockRadarPro:
    def __init__(self):
        self.db = DBManager()  # <--- 新增：启动数据库连接
        self.zt_data = {}
        self.zbgc_data = set()
        self.today = datetime.datetime.now().strftime("%Y%m%d")
        # self.today = "20260123" # 调试用
        print(f"{Fore.CYAN}[初始化] 模式: {self.get_strategy_name()} | 日期: {self.today}{Style.RESET_ALL}")
        self._refresh_limit_pool()

    def get_strategy_name(self):
        names = {1: "早盘强势追涨", 2: "尾盘潜伏低吸", 3: "冲击涨停博弈", 0: "全市场扫描"}
        strategy_ids = StrategyFilter.normalize_strategy_ids(CURRENT_STRATEGY)
        if not strategy_ids:
            return names.get(0, "全市场扫描")
        return " / ".join([names[sid] for sid in strategy_ids])

    def _refresh_limit_pool(self):
        try:
            df_zt = ak.stock_zt_pool_em(date=self.today)
            if not df_zt.empty:
                self.zt_data = dict(zip(df_zt['代码'].astype(str), df_zt['连板数']))

            df_zb = ak.stock_zt_pool_zbgc_em(date=self.today)
            if not df_zb.empty:
                self.zbgc_data = set(df_zb['代码'].astype(str).tolist())
        except:
            pass

    def _get_limit_threshold(self, code, name):
        if "ST" in name: return 4.9
        if code.startswith("8") or code.startswith("4"): return 29.5
        if code.startswith("688") or code.startswith("30"): return 19.5
        return 9.8

    def _is_one_word_board(self, high, low, pct, threshold):
        return (high == low) and (pct > threshold)

    def scan_hot_concepts(self, top_n=3):
        """
        获取热点板块 (三级灾备方案)
        优先级: 同花顺概念 > 东方财富概念 > 东方财富行业
        """
        # ============================================
        # 方案 A: 同花顺概念 (THS) - 短线首选
        # ============================================
        try:
            # print("正在尝试同花顺概念...")
            df = ak.stock_board_concept_name_ths()
            if not df.empty and '涨跌幅' in df.columns:
                df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
                df = df.rename(columns={'概念名称': '板块名称'})
                return df.sort_values(by="涨跌幅", ascending=False).head(top_n)
        except:
            pass # A计划失败，静默转B计划

        # ============================================
        # 方案 B: 东方财富概念 (EM) - 最佳替补
        # ============================================
        try:
            print(f"{Fore.YELLOW}⚠️ 同花顺接口波动，正在切换至【东方财富概念】源...{Style.RESET_ALL}")
            df = ak.stock_board_concept_name_em()
            if not df.empty:
                # 东方财富的列名通常是 '板块名称', '涨跌幅'
                return df.sort_values(by="涨跌幅", ascending=False).head(top_n)
        except Exception as e:
            # print(f"EM概念获取失败: {e}")
            pass

        # ============================================
        # 方案 C: 东方财富行业 (Industry) - 最后的保底
        # ============================================
        print(f"{Fore.RED}⚠️ 概念数据全线异常，降级至【行业板块】(颗粒度较粗){Style.RESET_ALL}")
        try:
            df = ak.stock_board_industry_name_em()
            if not df.empty:
                return df.sort_values(by="涨跌幅", ascending=False).head(top_n)
        except:
            return pd.DataFrame() # 彻底没救了，返回空

    def deep_dive_concept(self, concept_name):
        """
        深入概念挖掘 (CLI版 - 双源兜底 + 数据库存储 + 板块效应)
        逻辑：THS (同花顺) -> 失败 -> EM (东方财富)
        """
        try:
            df = pd.DataFrame()

            # --- 1. 尝试同花顺接口 (数据最全) ---
            try:
                df = ak.stock_board_concept_cons_ths(symbol=concept_name)
            except:
                pass

            # --- 2. 如果同花顺失败，尝试东方财富 (备胎) ---
            if df.empty:
                try:
                    # print(f"  (THS无数据，切换EM源: {concept_name})") # 调试用
                    df = ak.stock_board_concept_cons_em(symbol=concept_name)
                except:
                    pass

            # 如果两个源都挂了，直接返回
            if df.empty:
                return []

            # --- 3. 数据标准化清洗 (兼容 THS 和 EM 的字段差异) ---
            # 关键字段强制转数字
            cols_to_numeric = ['涨跌幅', '现价', '最高', '最低', '换手', '量比', '最新涨跌幅']
            for col in cols_to_numeric:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # 兼容字段名: EM叫 '最新涨跌幅', THS叫 '涨跌幅'
            if '涨跌幅' not in df.columns and '最新涨跌幅' in df.columns:
                df['涨跌幅'] = df['最新涨跌幅']

            # 扩大扫描范围：只看前 10 名
            df_sorted = df.sort_values(by="涨跌幅", ascending=False).head(10)

            candidates = []  # 暂存符合策略的候选股

            for _, row in df_sorted.iterrows():
                code = str(row['代码'])
                name = row['名称']
                # 使用 get 防止 EM 接口缺失字段
                pct = row.get('涨跌幅', 0)
                price = row.get('现价', 0)
                high = row.get('最高', price)
                low = row.get('最低', price)
                turnover = row.get('换手', 0)

                # 1. 基础硬性过滤
                if "ST" in name: continue

                threshold = self._get_limit_threshold(code, name)

                # 2. 剔除一字板
                if self._is_one_word_board(high, low, pct, threshold):
                    continue

                # ==========================================
                # 🧠 调用 strategies.py 进行筛选
                # ==========================================
                is_selected = True
                strategy_tag = ""

                strategy_ids = StrategyFilter.normalize_strategy_ids(CURRENT_STRATEGY)
                if strategy_ids:
                    is_selected, strategy_tag = StrategyFilter.apply_strategies(row, threshold, strategy_ids)

                # 只有符合策略的才放入候选池
                if is_selected:
                    # 补充连板信息
                    streak_info = ""
                    if code in self.zt_data:
                        streak = self.zt_data[code]
                        streak_info = f"🔥{streak}板"
                    elif code in self.zbgc_data:
                        streak_info = "💣炸板"

                    # 💾 核心修改：存入数据库！
                    # ----------------------------------------------
                    clean_strategy = strategy_tag.replace("🚀", "").replace("🐟", "").replace("⚡", "").strip()
                    clean_concept = concept_name

                    # 确保 self.db 存在再调用，防止未初始化报错
                    if hasattr(self, 'db'):
                        self.db.save_candidate(
                            date=self.today,
                            code=code,
                            name=name,
                            strategy=clean_strategy,
                            concept=clean_concept,
                            price=price,
                            pct=pct
                        )

                    # 将所有信息打包存起来，暂时不打印
                    candidates.append({
                        "code": code,
                        "name": name,
                        "pct": pct,
                        "price": price,
                        "turnover": turnover,
                        "strategy_tag": strategy_tag,
                        "streak_info": streak_info,
                        "color": Fore.YELLOW  # 默认颜色
                    })

            # ==========================================
            # 🌪️ 板块效应计算 (Sector Effect Logic)
            # ==========================================
            final_results = []
            count = len(candidates)

            # 如果整个板块一只符合策略的都没有
            if count == 0:
                return []

            # 根据数量判定板块强度
            sector_tag = ""
            if count >= 3:
                sector_tag = f"{Fore.RED}[🔥板块爆发/集团军]"
            elif count == 2:
                sector_tag = f"{Fore.MAGENTA}[🤝双龙并进]"
            else:
                sector_tag = f"{Fore.BLUE}[⚠️独苗/需谨慎]"

            # 格式化输出
            for cand in candidates:
                # 如果是独苗，把名字标蓝提醒风险；如果是集团军，标红
                color = Fore.RED if count >= 3 else (Fore.YELLOW if count == 2 else Fore.CYAN)

                display_str = (
                    f"  {cand['strategy_tag']} {color}[{cand['code']}] {cand['name']} "
                    f"涨幅:{cand['pct']:>5.2f}% {cand['streak_info']} "
                    f"现价:{cand['price']} 换手:{cand['turnover']:.1f}% {sector_tag}{Style.RESET_ALL}"
                )
                final_results.append(display_str)

            return final_results

        except Exception as e:
            # print(f"处理异常: {e}") # 调试时可打开
            return []

    def run(self):
        global CURRENT_STRATEGY

        print("\n" + "=" * 50)
        print(f"🚀 A股短线雷达 | 策略: {self.get_strategy_name()} | {datetime.datetime.now().strftime('%H:%M:%S')}")
        print("=" * 50)
        # ==========================================
        # 🚦 第一步：调用 sentiment.py 看红绿灯 (新增)
        # ==========================================
        # 传入 self.today 以获取正确的“昨日涨停”数据
        mood_data = MarketSentiment.check_mood(self.today)
        mood_level = mood_data['level']  # 获取红绿灯状态

        strategy_ids = resolve_strategy_ids(mood_level, CURRENT_STRATEGY)
        if AUTO_STRATEGY:
            CURRENT_STRATEGY = strategy_ids
            print(f"{Fore.CYAN}[策略] 情绪:{mood_level} -> {self.get_strategy_name()}{Style.RESET_ALL}")

        # 💾 保存情绪数据到数据库
        self.db.save_mood(
            self.today,
            mood_data['sh_pct'],
            mood_data['premium'],
            mood_level
        )

        if mood_level == -1:
            print(f"\n{Fore.RED}⛔ 触发熔断机制...{Style.RESET_ALL}")
            return

        if len(self.zt_data) == 0: self._refresh_limit_pool()

        concepts = self.scan_hot_concepts(top_n=3)
        if concepts.empty:
            print("无法获取数据或休市。")
            return

        for i, row in concepts.iterrows():
            c_name = row.get('概念名称', row.get('板块名称'))
            c_pct = row['涨跌幅']

            print(f"\n📂 TOP {i + 1}: 【{c_name}】 (涨幅: {c_pct}%)")
            print("-" * 40)

            stock_list = self.deep_dive_concept(c_name)
            if stock_list:
                for s in stock_list: print(s)
            else:
                print("  (无符合策略的个股)")


if __name__ == "__main__":
    radar = StockRadarPro()
    radar.run()
