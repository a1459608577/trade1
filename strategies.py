# strategies.py
# -*- coding: utf-8 -*-

import math

class StrategyFilter:
    """
    短线选股策略集合 (Pro 优化版)
    优化核心：增加市值过滤、量比过滤、换手率要求，剔除假强股。
    """

    @staticmethod
    def _safe_num(value, default=0.0):
        try:
            num = float(value)
            if math.isnan(num):
                return default
            return num
        except (TypeError, ValueError):
            return default

    @staticmethod
    def calculate_pre_close(price, pct):
        """辅助：倒推昨收"""
        if price == 0: return 0
        return price / (1 + pct / 100)

    @staticmethod
    def _calc_amplitude(high, low, price, pct, row=None):
        """优先使用接口自带振幅，没有则用高低价估算"""
        if row is not None:
            amp = StrategyFilter._safe_num(row.get('振幅', 0), 0)
            if amp > 0:
                return amp
        pre_close = StrategyFilter.calculate_pre_close(price, pct)
        if pre_close == 0:
            return 0
        return (high - low) / pre_close * 100

    @staticmethod
    def normalize_strategy_ids(strategy):
        """将策略配置规范为有序ID列表，空列表代表不筛选"""
        if strategy is None:
            return []
        if isinstance(strategy, (list, tuple, set)):
            ids = []
            for item in strategy:
                try:
                    sid = int(item)
                except (TypeError, ValueError):
                    continue
                if sid in (1, 2, 3):
                    ids.append(sid)
            return sorted(set(ids))
        try:
            sid = int(strategy)
        except (TypeError, ValueError):
            return []
        if sid in (1, 2, 3):
            return [sid]
        return []

    @staticmethod
    def apply_strategies(row, limit_threshold, strategy_ids):
        """多策略联合筛选，命中任意策略即返回 True"""
        tags = []
        for sid in strategy_ids:
            if sid == 1:
                ok, tag = StrategyFilter.check_strong_chase(row, limit_threshold)
            elif sid == 2:
                ok, tag = StrategyFilter.check_tail_end_lurk(row, limit_threshold)
            elif sid == 3:
                ok, tag = StrategyFilter.check_weak_to_strong(row, limit_threshold)
            else:
                ok, tag = False, ""
            if ok:
                tags.append(tag)
        if tags:
            return True, " / ".join(tags)
        return False, ""

    @staticmethod
    def check_strong_chase(row, limit_threshold):
        """
        策略 1: 【早盘强势追涨】(Pro版)
        场景: 9:30 - 10:30
        优化:
        1. 涨幅处于强势启动区间
        2. 放量 + 合理换手，避免假强
        3. 上影线短，回撤小
        """
        pct = StrategyFilter._safe_num(row.get('涨跌幅', 0), 0)
        turnover = StrategyFilter._safe_num(row.get('换手', 0), 0)
        volume_ratio = StrategyFilter._safe_num(row.get('量比', 0), 0)
        price = StrategyFilter._safe_num(row.get('现价', 0), 0)
        high = StrategyFilter._safe_num(row.get('最高', price), price)
        low = StrategyFilter._safe_num(row.get('最低', price), price)
        # 注意：部分接口 '流通市值' 单位不统一，这里假设AkShare返回的是亿或万，需根据实际调整
        # 这里暂不加硬性市值过滤，依靠换手率来筛选活跃度

        # 1. 涨幅区间：强势启动但不临涨停
        upper = limit_threshold * 0.85
        if not (4.5 <= pct <= upper):
            return False, ""

        # 2. 换手率：有人气但不过热
        if not (4.0 <= turnover <= 20.0):
            return False, ""

        # 3. 放量要求：量比不足直接排除 (没量的强势容易回落)
        if volume_ratio > 0 and volume_ratio < 1.3:
            return False, ""

        # 4. 形态过滤：上影线短 + 振幅不过大
        if high > 0 and price > 0 and (high - price) / price > 0.015:
            return False, ""
        amplitude = StrategyFilter._calc_amplitude(high, low, price, pct, row)
        if amplitude > 7.5:
            return False, ""

        return True, "🚀 [强势追涨]"

    @staticmethod
    def check_tail_end_lurk(row, limit_threshold):
        """
        策略 2: 【尾盘潜伏博弈】(Pro版)
        场景: 14:30 - 14:55
        优化:
        1. 走势温和，避免情绪冲顶
        2. 振幅小 + 收盘强度高
        3. 量能稳定，避免突然异动
        """
        pct = StrategyFilter._safe_num(row.get('涨跌幅', 0), 0)
        high = StrategyFilter._safe_num(row.get('最高', 0), 0)
        low = StrategyFilter._safe_num(row.get('最低', 0), 0)
        price = StrategyFilter._safe_num(row.get('现价', 0), 0)
        turnover = StrategyFilter._safe_num(row.get('换手', 0), 0)
        volume_ratio = StrategyFilter._safe_num(row.get('量比', 0), 0)

        # 1. 涨幅温和：避免接情绪高点
        if not (1.5 <= pct <= 6.0):
            return False, ""

        # 2. 振幅控制：越小越稳
        amplitude = StrategyFilter._calc_amplitude(high, low, price, pct, row)
        if amplitude > 4.0:
            return False, ""

        # 3. 收盘位置：靠近全天最高点
        if high > 0 and price < (high * 0.985):
            return False, ""

        # 4. 换手率：不能是死股，也不宜过热
        if not (1.5 <= turnover <= 10.0):
            return False, ""

        # 5. 量能稳定：过弱或爆量都不适合潜伏
        if volume_ratio > 0 and not (0.8 <= volume_ratio <= 2.5):
            return False, ""

        # 6. 临涨停的票不适合潜伏
        if pct >= (limit_threshold - 1.5):
            return False, ""

        return True, "🐟 [尾盘潜伏]"

    @staticmethod
    def check_weak_to_strong(row, limit_threshold):
        """
        策略 3: 【冲击涨停/弱转强】(Pro版)
        场景: 全天，风险偏好极高
        优化:
        1. 必须是“有准备”的冲板 (换手够)
        2. 剔除几十元的高价股 (散户跟风难，封板难)
        3. 形态强势，收盘靠近高点
        """
        pct = StrategyFilter._safe_num(row.get('涨跌幅', 0), 0)
        price = StrategyFilter._safe_num(row.get('现价', 0), 0)
        high = StrategyFilter._safe_num(row.get('最高', price), price)
        low = StrategyFilter._safe_num(row.get('最低', price), price)
        turnover = StrategyFilter._safe_num(row.get('换手', 0), 0)
        volume_ratio = StrategyFilter._safe_num(row.get('量比', 0), 0)

        # 1. 攻击形态：涨幅达到冲板区间
        lower = max(6.5, limit_threshold * 0.5)
        if not (lower <= pct < (limit_threshold - 0.3)):
            return False, ""

        # 2. 价格心理学：剔除 80元 以上的高价股 (游资不喜欢接力高价)
        if price > 80:
            return False, ""

        # 3. 换手率底线：冲击涨停必须要有换手
        if turnover < 6.0:
            return False, ""

        # 4. 放量确认：没有放量的冲板易炸
        if volume_ratio > 0 and volume_ratio < 1.4:
            return False, ""

        # 5. 强势形态：收盘靠近最高点 + 振幅不过分
        if high > 0 and price > 0 and (high - price) / price > 0.01:
            return False, ""
        amplitude = StrategyFilter._calc_amplitude(high, low, price, pct, row)
        if amplitude > 14.0:
            return False, ""

        return True, "⚡ [冲击涨停]"
