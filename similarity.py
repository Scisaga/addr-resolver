import thulac,difflib
import re

thu = thulac.thulac(seg_only=True)

def string_similarity(a: str, b: str) -> float:
    """计算两个字符串之间的相似度（0~1）"""
    return difflib.SequenceMatcher(None, a, b).ratio()

def extract_keyword_sequence(address: str):
    """
    使用 jieba 分词 + 停用词过滤提取关键词
    """
    if isinstance(address, list):  # 防御性处理，防止传入 list
        address = ''.join(address)
    words = thu.cut(address)  # address 必须是 str
    keywords = [w[0] for w in words if len(w[0].strip()) >= 2]
    return keywords

def score_main_tokens(addr_a: str, addr_b: str):
    """
    匹配得分 = Σ（匹配词的加权长度）/ max(总长度A, 总长度B)
    - 完全匹配：加上词长
    - 部分匹配：加上 词长 * 相似度
    """
    keywords_a = extract_keyword_sequence(addr_a)
    keywords_b = extract_keyword_sequence(addr_b)

    if not keywords_a and not keywords_b:
        return 1.0
    if not keywords_a or not keywords_b:
        return 0.0

    total_len_a = sum(len(w) for w in keywords_a)
    total_len_b = sum(len(w) for w in keywords_b)

    matched_score = 0.0

    for word_a in keywords_a:
        best_sim = 0.0
        for word_b in keywords_b:
            sim = string_similarity(word_a, word_b)
            if sim > best_sim:
                best_sim = sim
        # 加分 = 词长 × 相似度（完全匹配则为 1）
        matched_score += len(word_a) * best_sim

    final_score = matched_score / max(total_len_a, total_len_b)
    return round(final_score, 4)

def extract_keyword_sequence_reg(text: str) -> list:
    """
    从地址中提取结构关键词列表，如“8号院”、“5号楼”、“D区”等
    """
    if not isinstance(text, str):
        return []
    patterns = [
        r"[A-Z]\d+", r"\d+号", r"\d+号楼", r"\d+号院", r"\d+单元", r"\d+室", r"[A-Z]座", r"[A-Z]区", r"[A-Z]馆",
        r"\d+号", r"[一二三四五六七八九十]+号楼", r"[一二三四五六七八九十]+单元"
    ]
    pattern = "|".join(patterns)
    return re.findall(pattern, text)


def extract_digit_alpha_seq_from_keywords(keywords: list) -> list:
    """
    从结构关键词中提取数字/字母序列，保留顺序
    """
    seq = []
    for kw in keywords:
        seq += re.findall(r'\d+|[A-Z]', kw.upper())
    return seq


def match_sequence_score(seq_a: list, seq_b: list) -> float:
    if not seq_a or not seq_b:
        return 0.0

    match_score = 0.0
    max_len = max(len(seq_a), len(seq_b))
    min_len = min(len(seq_a), len(seq_b))

    for i in range(min_len):
        sim = string_similarity(seq_a[i], seq_b[i])
        if sim >= 0.7:  # 相似度阈值
            match_score += sim  # 越相似加分越高

    return round(100 * match_score / max_len, 2)


def core_keyword_overlap_ratio(a: str, b: str) -> float:
    """
    对两个地址中的结构关键词（楼栋/单元/楼层等）做顺序匹配评分
    """
    kws_a = extract_keyword_sequence_reg(a)
    kws_b = extract_keyword_sequence_reg(b)

    seq_a = extract_digit_alpha_seq_from_keywords(kws_a)
    seq_b = extract_digit_alpha_seq_from_keywords(kws_b)

    if not seq_a or not seq_b:
        return 0.0

    forward = match_sequence_score(seq_a, seq_b)
    backward = match_sequence_score(seq_a[::-1], seq_b[::-1])
    return max(forward, backward)

if __name__ == "__main__":
    # 示例
    addr1 = "海曙区集士港镇三江购物"
    addr2 = "三江购物(集仕港杰迈广场店)"

    print("关键词 A:", extract_keyword_sequence(addr1))
    print("关键词 B:", extract_keyword_sequence(addr2))
    print("得分:", score_main_tokens(addr1, addr2))

    addr1 = "海曙区集士港镇三江购物"
    addr2 = "三江购物(集仕东路店) "

    print("关键词 A:", extract_keyword_sequence(addr1))
    print("关键词 B:", extract_keyword_sequence(addr2))
    print("得分:", score_main_tokens(addr1, addr2))