import math

def distance(lat1, lon1, lat2, lon2):
    """
    根据经纬度计算球面距离（单位：公里）
    输入参数单位：十进制度数
    """
    # 地球半径（km）
    R = 6371.0  
    
    # 转弧度
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    # Haversine 公式
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c