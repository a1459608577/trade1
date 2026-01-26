# stock_radar.py
# -*- coding: utf-8 -*-

import akshare as ak
import pandas as pd
import datetime
import time
import random  # 引入随机库
import sys
from colorama import init, Fore, Style
from strategies import StrategyFilter
from sentiment import MarketSentiment
from db_manager import DBManager

init(autoreset=True)
pd.set_option('display.max_columns', None)
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)

# ==========================================
# ⚙️ 策略配置
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


class StockRadarPro:
    def __init__(self):
        self.db = DBManager()
        self.zt_data = {}
        self.zbgc_data = set()

        # ⚠️ 调试模式：强制指定一个历史交易日 (防止周末/盘前无数据)
        # 等调试通了，再改回 datetime.datetime.now().strftime("%Y%m%d")
        # self.today = "20240124"  # 请修改为你想要测试的日期（如上周五）
        self.today = datetime.datetime.now().strftime("%Y%m%d")

        print(f"{Fore.CYAN}[初始化] 模式: {self.get_strategy_name()} | 日期: {self.today}{Style.RESET_ALL}")

        # 初始化涨停池 (带报错提示)
        self._refresh_limit_pool()

    def get_strategy_name(self):
        names = {1: "早盘强势追涨", 2: "尾盘潜伏低吸", 3: "冲击涨停博弈", 0: "全市场扫描"}
        strategy_ids = StrategyFilter.normalize_strategy_ids(CURRENT_STRATEGY)
        if not strategy_ids:
            return names.get(0, "全市场扫描")
        return " / ".join([names[sid] for sid in strategy_ids])

    def _refresh_limit_pool(self):
        print(">> 正在获取涨停/炸板数据...")
        try:
            df_zt = ak.stock_zt_pool_em(date=self.today)
            if not df_zt.empty:
                self.zt_data = dict(zip(df_zt['代码'].astype(str), df_zt['连板数']))
                print(f"✅ 涨停数据加载成功: {len(self.zt_data)} 条")
            else:
                print(f"{Fore.YELLOW}⚠️ 今日无涨停数据 (可能是休市或数据未更新){Style.RESET_ALL}")

            df_zb = ak.stock_zt_pool_zbgc_em(date=self.today)
            if not df_zb.empty:
                self.zbgc_data = set(df_zb['代码'].astype(str).tolist())
        except Exception as e:
            print(f"{Fore.RED}❌ 获取涨停池失败: {e}{Style.RESET_ALL}")

    def _get_limit_threshold(self, code, name):
        if "ST" in name: return 4.9
        if code.startswith("8") or code.startswith("4"): return 29.5
        if code.startswith("688") or code.startswith("30"): return 19.5
        return 9.8

    def _is_one_word_board(self, high, low, pct, threshold):
        return (high == low) and (pct > threshold)

    def scan_hot_concepts(self, top_n=3):
        """
        获取热点板块 (修正版：修复新浪源名称为英文代码的问题)
        """
        # ============================================
        # 方案 A: 新浪行业板块 (Sina Industry) - 首选
        # ============================================
        try:
            print(f"1️⃣ 尝试 [新浪行业] 接口...")
            df = ak.stock_sector_spot(indicator="新浪行业")

            if not df.empty:
                # print(f"调试列名: {df.columns.tolist()}") # 调试用

                # ✅ 修正点：只映射 'name' 到 '板块'
                # label 是英文代码(new_ysjs)，name 是中文(有色金属)
                rename_dict = {
                    'name': '板块',
                    'percent': '涨跌幅'
                }
                df = df.rename(columns=rename_dict)

                # 确保必须有中文名称列
                if '板块' in df.columns and '涨跌幅' in df.columns:
                    df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
                    print(f"✅ 新浪行业获取成功: {len(df)} 条")
                    return df.sort_values(by="涨跌幅", ascending=False).head(top_n)
                else:
                    print(f"⚠️ 接口返回字段不匹配，可用字段: {df.columns.tolist()}")

        except Exception as e:
            print(f"❌ [Sina行业] 失败: {e}")

        # ============================================
        # 方案 B: 新浪概念板块 (Sina Concept) - 备选
        # ============================================
        try:
            print(f"2️⃣ 尝试 [新浪概念] 接口...")
            df = ak.stock_sector_spot(indicator="新浪概念")

            if not df.empty:
                # ✅ 修正点：同样只映射 'name'
                rename_dict = {
                    'name': '板块',
                    'percent': '涨跌幅'
                }
                df = df.rename(columns=rename_dict)

                if '板块' in df.columns:
                    df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
                    print(f"✅ 新浪概念获取成功: {len(df)} 条")
                    return df.sort_values(by="涨跌幅", ascending=False).head(top_n)

        except Exception as e:
            print(f"❌ [Sina概念] 失败: {e}")

        # ============================================
        # 方案 C: 东方财富行业 (保底)
        # ============================================
        try:
            print(f"3️⃣ 尝试 [东方财富行业] 接口...")
            df = ak.stock_board_industry_name_em()
            if not df.empty and '涨跌幅' in df.columns:
                df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
                print(f"✅ EM行业获取成功: {len(df)} 条")
                return df.sort_values(by="涨跌幅", ascending=False).head(top_n)
        except Exception as e:
            pass

        print(f"{Fore.RED}⛔ 所有数据源均不可用，请检查网络连接！{Style.RESET_ALL}")
        return pd.DataFrame()

    def deep_dive_concept(self, concept_name):
        """
        深入概念挖掘 (修复版：弃用 THS，全线转用 EM)
        """
        # 🟢 随机延迟，防止被封 IP
        time.sleep(random.uniform(0.5, 1.0))

        try:
            df = pd.DataFrame()

            # ============================================
            # 方案 A: 东方财富概念成分股 (首选)
            # ============================================
            try:
                # print(f"  > 尝试 EM 概念成分股: {concept_name}...")
                df = ak.stock_board_concept_cons_em(symbol=concept_name)
            except Exception as e:
                # print(f"    EM概念失败: {e}")
                pass

            # ============================================
            # 方案 B: 东方财富行业成分股 (备选)
            # ============================================
            if df.empty:
                try:
                    # print(f"  > 尝试 EM 行业成分股: {concept_name}...")
                    df = ak.stock_board_industry_cons_em(symbol=concept_name)
                except Exception as e:
                    pass

            # ============================================
            # 方案 C: 同花顺 (已废弃，直接移除)
            # ============================================
            # 旧接口 ak.stock_board_concept_cons_ths 已失效，不再尝试

            if df.empty:
                # print(f"{Fore.YELLOW}  ⚠️ 无法获取板块【{concept_name}】的成分股{Style.RESET_ALL}")
                return []

            # --- 数据清洗与标准化的逻辑 (保持不变) ---

            # 1. 统一列名 (EM 返回的列名可能是 '最新涨跌幅')
            rename_map = {
                '最新涨跌幅': '涨跌幅',
                '最新价': '现价',
                '代码': '代码',
                '名称': '名称',
                '换手率': '换手',
                '量比': '量比'
            }
            # 仅重命名存在的列
            df = df.rename(columns=rename_map)

            # 2. 确保关键字段是数字
            cols_to_numeric = ['涨跌幅', '现价', '最高', '最低', '换手', '量比']
            for col in cols_to_numeric:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # 3. 排序取前10
            if '涨跌幅' in df.columns:
                df_sorted = df.sort_values(by="涨跌幅", ascending=False).head(10)
            else:
                return []

            candidates = []

            for _, row in df_sorted.iterrows():
                try:
                    code = str(row['代码'])
                    name = row['名称']
                    pct = row.get('涨跌幅', 0)
                    price = row.get('现价', 0)
                    high = row.get('最高', price)
                    low = row.get('最低', price)
                    turnover = row.get('换手', 0)

                    if "ST" in name: continue
                    threshold = self._get_limit_threshold(code, name)

                    if self._is_one_word_board(high, low, pct, threshold):
                        continue

                    is_selected = True
                    strategy_tag = ""

                    strategy_ids = StrategyFilter.normalize_strategy_ids(CURRENT_STRATEGY)
                    if strategy_ids:
                        is_selected, strategy_tag = StrategyFilter.apply_strategies(row, threshold, strategy_ids)

                    if is_selected:
                        streak_info = ""
                        if code in self.zt_data:
                            streak = self.zt_data[code]
                            streak_info = f"🔥{streak}板"
                        elif code in self.zbgc_data:
                            streak_info = "💣炸板"

                        # 存入数据库
                        if hasattr(self, 'db'):
                            clean_strategy = strategy_tag.replace("🚀", "").replace("🐟", "").replace("⚡", "").strip()
                            self.db.save_candidate(self.today, code, name, clean_strategy, concept_name, price, pct)

                        candidates.append({
                            "code": code,
                            "name": name,
                            "pct": pct,
                            "price": price,
                            "turnover": turnover,
                            "strategy_tag": strategy_tag,
                            "streak_info": streak_info
                        })
                except Exception:
                    continue

            # 输出展示
            final_results = []
            count = len(candidates)
            if count == 0: return []

            sector_tag = ""
            if count >= 3:
                sector_tag = f"{Fore.RED}[🔥板块爆发]"
            elif count == 2:
                sector_tag = f"{Fore.MAGENTA}[🤝双龙并进]"
            else:
                sector_tag = f"{Fore.BLUE}[⚠️独苗]"

            for cand in candidates:
                color = Fore.YELLOW
                if count >= 3: color = Fore.MAGENTA

                display_str = (
                    f"  {cand['strategy_tag']} {color}[{cand['code']}] {cand['name']} "
                    f"涨幅:{cand['pct']:>5.2f}% {cand['streak_info']} "
                    f"现价:{cand['price']} 换{cand['turnover']:.1f}% {sector_tag}{Style.RESET_ALL}"
                )
                final_results.append(display_str)

            return final_results

        except Exception as e:
            print(f"❌ 板块挖掘报错: {e}")
            return []

    def run(self):
        global CURRENT_STRATEGY

        print("\n" + "=" * 50)
        print(f"🚀 A股短线雷达 | 策略: {self.get_strategy_name()} | {datetime.datetime.now().strftime('%H:%M:%S')}")
        print("=" * 50)

        # 情绪检测
        mood_data = MarketSentiment.check_mood(self.today)
        mood_level = mood_data.get('level', 0)  # 使用 get 防止报错

        strategy_ids = resolve_strategy_ids(mood_level, CURRENT_STRATEGY)
        if AUTO_STRATEGY:
            CURRENT_STRATEGY = strategy_ids
            print(f"{Fore.CYAN}[策略] 情绪:{mood_level} -> {self.get_strategy_name()}{Style.RESET_ALL}")

        self.db.save_mood(self.today, mood_data.get('sh_pct', 0), mood_data.get('premium', 0), mood_level)

        if mood_level == -1:
            print(f"\n{Fore.RED}⛔ 触发熔断机制...{Style.RESET_ALL}")
            return

        if len(self.zt_data) == 0: self._refresh_limit_pool()

        # 扫描板块
        concepts = self.scan_hot_concepts(top_n=3)
        if concepts.empty:
            print(f"{Fore.RED}❌ 无法获取任何板块数据，程序提前终止。{Style.RESET_ALL}")
            return

        for i, row in concepts.iterrows():
            c_name = row.get('概念名称', row.get('板块'))
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