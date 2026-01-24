# strategies.py
# -*- coding: utf-8 -*-

class StrategyFilter:
    """
    短线选股策略集合 (Pro 优化版)
    优化核心：增加市值过滤、量比过滤、换手率要求，剔除假强股。
    """

    @staticmethod
    def calculate_pre_close(price, pct):
        """辅助：倒推昨收"""
        if price == 0: return 0
        return price / (1 + pct / 100)

    @staticmethod
    def check_strong_chase(row, limit_threshold):
        """
        策略 1: 【早盘强势追涨】(Pro版)
        场景: 9:30 - 10:30
        优化:
        1. 只要小盘股 (弹性大)
        2. 必须放量 (量比 > 1.2)
        3. 拒绝上影线 (收盘价必须接近最高价)
        """
        pct = row['涨跌幅']
        turnover = row.get('换手', 0)
        price = row.get('现价', 0)
        high = row.get('最高', price)
        # 注意：部分接口 '流通市值' 单位不统一，这里假设AkShare返回的是亿或万，需根据实际调整
        # 这里暂不加硬性市值过滤，依靠换手率来筛选活跃度

        # 1. 涨幅区间：4% - 8% (放宽一点下限，抓启动)
        if not (4.0 <= pct <= 8.5):
            return False, ""

        # 2. 必须未封板 (给 1% 的空间，防止买在排队中)
        if pct >= (limit_threshold - 1.0):
            return False, ""

        # 3. 换手率: 必须 > 4% (说明有人气)，且 < 18% (太大说明分歧大，容易炸)
        if not (4.0 <= turnover <= 18.0):
            return False, ""

        # 4. 形态过滤：拒绝长上影线
        # 如果 (最高价 - 现价) / 现价 > 2%，说明冲高回落了，不要接盘
        if high > 0 and (high - price) / price > 0.02:
            return False, ""

        return True, "🚀 [强势追涨]"

    @staticmethod
    def check_tail_end_lurk(row, limit_threshold):
        """
        策略 2: 【尾盘潜伏博弈】(Pro版)
        场景: 14:30 - 14:55
        优化:
        1. 必须是抗跌的 (大盘跌它不跌)
        2. 筹码必须稳定 (振幅小)
        """
        pct = row['涨跌幅']
        high = row['最高']
        low = row['最低']
        price = row['现价']
        turnover = row.get('换手', 0)

        # 1. 涨幅温和：2% - 5% (太高了没性价比，太低了没势能)
        if not (2.0 <= pct <= 5.5):
            return False, ""

        # 2. 振幅控制：必须小于 4%
        # 振幅 = (最高-最低) / 昨收
        pre_close = StrategyFilter.calculate_pre_close(price, pct)
        if pre_close == 0: return False, ""

        amplitude = (high - low) / pre_close * 100
        if amplitude > 4.5:
            return False, ""

        # 3. 收盘位置：必须收在全天最高点附近 (主力护盘)
        # 允许回落 1% 以内
        if price < (high * 0.99):
            return False, ""

        # 4. 换手率：潜伏不需要太高换手，但不能是死股
        if turnover < 2.0:
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
        """
        pct = row['涨跌幅']
        price = row['现价']
        turnover = row.get('换手', 0)

        # 1. 攻击形态：涨幅 > 7.5%
        if not (7.5 <= pct < limit_threshold):
            return False, ""

        # 2. 价格心理学：剔除 80元 以上的高价股 (游资不喜欢接力高价)
        if price > 80:
            return False, ""

        # 3. 换手率底线：冲击涨停必须要有换手 (>5%)
        # 如果换手只有 1%，那是缩量加速，一旦炸板就是天地板，风险太大
        if turnover < 5.0:
            return False, ""

        return True, "⚡ [冲击涨停]"