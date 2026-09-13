"""掌握度规则的纯领域实现。"""

from collections.abc import Sequence


STRONG_RATE = 0.8
MID_RATE = 0.6


def propose_from_rates(rates: Sequence[float]) -> dict:
    """按最近会话正确率计算掌握度建议。

    rates 必须按时间倒序排列，最近会话在前。规则：
    - strong：最近两个会话正确率均 >= 0.8
    - mid：最近一次会话正确率 >= 0.6
    - weak：其余情况
    """
    normalized = [float(rate) for rate in rates]
    sessions = len(normalized)
    if sessions >= 2 and normalized[0] >= STRONG_RATE and normalized[1] >= STRONG_RATE:
        level = "strong"
    elif sessions >= 1 and normalized[0] >= MID_RATE:
        level = "mid"
    else:
        level = "weak"

    if sessions == 0:
        confidence, evidence = 0.0, "无作答记录"
    elif sessions == 1:
        confidence = round(normalized[0], 2)
        evidence = f"练过1次/最近一次正确率 {normalized[0]:.0%}"
    else:
        confidence = round(normalized[0], 2)
        evidence = (
            f"练过{sessions}次/最近两次正确率 "
            f"{normalized[1]:.0%}→{normalized[0]:.0%}"
        )
    return {
        "suggest_level": level,
        "confidence": confidence,
        "evidence": evidence,
        "sessions": sessions,
    }
