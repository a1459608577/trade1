# sentiment.py
# -*- coding: utf-8 -*-

import akshare as ak
import pandas as pd
from colorama import Fore, Style


class MarketSentiment:
    """
    市场情绪监控模块
    负责判断大盘环境，决定是否熔断
    """

    @staticmethod
    def check_mood(date_str):
        """
        返回市场情绪状态 (统一返回字典结构)
        """
        print(f"{Fore.CYAN}>> 正在检测全市场情绪 (Market Mood)...{Style.RESET_ALL}")

        # 默认返回结构（防止中途报错导致变量未定义）
        result = {
            "level": 0,  # 0=震荡(默认)
            "sh_pct": 0.0,
            "premium": 0.0
        }

        try:
            # 1. 检查大盘指数
            df_index = ak.stock_zh_index_spot_sina()
            sh_index = df_index[df_index['代码'] == 'sh000001']

            sh_pct = 0.0
            if not sh_index.empty:
                sh_pct = float(sh_index.iloc[0]['涨跌幅'])

            # 2. 检查短线情绪
            try:
                df_prev_zt = ak.stock_zt_pool_previous_em(date=date_str)
            except:
                df_prev_zt = pd.DataFrame()

            avg_premium = 0.0
            if not df_prev_zt.empty:
                col_name = '最新涨跌幅' if '最新涨跌幅' in df_prev_zt.columns else '涨跌幅'
                if col_name in df_prev_zt.columns:
                    df_prev_zt[col_name] = pd.to_numeric(df_prev_zt[col_name], errors='coerce')
                    avg_premium = df_prev_zt[col_name].mean()

            # 打印信息
            print(f"   [指数] 上证涨幅: {MarketSentiment._color_num(sh_pct)}%")
            print(f"   [情绪] 昨板溢价: {MarketSentiment._color_num(avg_premium)}%")

            # 更新结果数值
            result['sh_pct'] = sh_pct
            result['premium'] = avg_premium

            # 🚦 裁判逻辑
            # 🔴 红灯
            if avg_premium < -1.5 or sh_pct < -1.2:
                print(f"{Fore.RED}🔴 警告：市场情绪冰点！建议空仓！{Style.RESET_ALL}")
                result['level'] = -1
                return result

            # 🟢 绿灯
            if avg_premium > 1.5 and sh_pct > -0.3:
                print(f"{Fore.GREEN}🟢 信号：情绪高涨，大胆操作！{Style.RESET_ALL}")
                result['level'] = 1
                return result

            # 🟡 黄灯 (默认)
            print(f"{Fore.YELLOW}🟡 提示：市场情绪一般，控制仓位。{Style.RESET_ALL}")
            result['level'] = 0
            return result

        except Exception as e:
            # ⚠️ 核心修复点在这里！
            # 发生异常时，不要返回 0，而是返回一个安全的默认字典
            print(f"{Fore.YELLOW}⚠️ 情绪检测异常: {e} (已降级为默认状态){Style.RESET_ALL}")

            # 返回默认的“黄灯”字典，保证主程序不崩
            return {
                "level": 0,
                "sh_pct": 0.0,
                "premium": 0.0
            }

    @staticmethod
    def _color_num(num):
        """辅助函数：给数字上色"""
        s = f"{num:>5.2f}"
        if num > 0: return f"{Fore.RED}{s}{Style.RESET_ALL}"
        if num < 0: return f"{Fore.GREEN}{s}{Style.RESET_ALL}"
        return s