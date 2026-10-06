"""hnefatafl-lite: 简化版 Hnefatafl（11x11 维京棋）.

规则（简化，详见 README）:
- 11x11 棋盘。攻方 24 子（黑），守方 12 子 + 国王（白）。
- 车式走法：横竖走任意格，不可跳子。
- 夹吃（custodian capture）: 敌子被两枚己子（或己子+敌对格）
  在正交方向夹住即被吃。国王需四面被围才被吃（王座/边可作一面）。
- 只有国王能进入角落和王座；国王到达任意角落即守方胜。
- 攻方吃掉国王即攻方胜；一方无子可走判负。
"""

import argparse
import copy
import random
import sys

SIZE = 11
THRONE = (5, 5)
CORNERS = {(0, 0), (0, 10), (10, 0), (10, 10)}

ATTACKER = "A"
DEFENDER = "D"
KING = "K"
EMPTY = "."

DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]

# 攻方 24 子标准开局
_ATTACKER_SQUARES = (
    [(0, c) for c in range(3, 8)] + [(1, 5)]
    + [(10, c) for c in range(3, 8)] + [(9, 5)]
    + [(r, 0) for r in range(3, 8)] + [(5, 1)]
    + [(r, 10) for r in range(3, 8)] + [(5, 9)]
)
# 守方 12 子
_DEFENDER_SQUARES = [
    (3, 5), (4, 4), (4, 5), (4, 6),
    (5, 3), (5, 4), (5, 6), (5, 7),
    (6, 4), (6, 5), (6, 6), (7, 5),
]

MAX_HALF_MOVES = 600


def in_bounds(r, c):
    return 0 <= r < SIZE and 0 <= c < SIZE


def hostile_square(r, c, piece):
    """该格能否作为夹吃时的"颚"（对 piece 而言）.

    空王座和空角落对双方都算敌对格；只有国王能站在上面。
    """
    return (r, c) == THRONE or (r, c) in CORNERS


def new_game():
    board = [[EMPTY] * SIZE for _ in range(SIZE)]
    for r, c in _ATTACKER_SQUARES:
        board[r][c] = ATTACKER
    for r, c in _DEFENDER_SQUARES:
        board[r][c] = DEFENDER
    board[THRONE[0]][THRONE[1]] = KING
    return {"board": board, "turn": ATTACKER, "half": 0,
            "king_pos": THRONE, "seen": {}}


def is_attacker(p):
    return p == ATTACKER


def is_defender_side(p):
    return p in (DEFENDER, KING)


def rook_targets(board, r, c):
    """车式走法目标格（不含起点）。"""
    out = []
    for dr, dc in DIRS:
        nr, nc = r + dr, c + dc
        while in_bounds(nr, nc) and board[nr][nc] == EMPTY:
            # 只有国王能进入/穿过王座与角落
            if ((nr, nc) == THRONE or (nr, nc) in CORNERS) and board[r][c] != KING:
                break
            out.append((nr, nc))
            nr += dr
            nc += dc
    return out


def legal_moves(game, side=None):
    side = side or game["turn"]
    board = game["board"]
    moves = []
    for r in range(SIZE):
        for c in range(SIZE):
            p = board[r][c]
            if p == EMPTY:
                continue
            if side == ATTACKER and not is_attacker(p):
                continue
            if side != ATTACKER and not is_defender_side(p):
                continue
            for t in rook_targets(board, r, c):
                moves.append(((r, c), t))
    return moves


def _capture_after(board, tr, tc, mover_side):
    """走子落到 (tr,tc) 后被夹吃的敌子坐标列表（不含国王特殊规则）。"""
    mover = board[tr][tc]
    caps = []
    for dr, dc in DIRS:
        nr, nc = tr + dr, tc + dc
        br, bc = tr + 2 * dr, tc + 2 * dc
        if not in_bounds(nr, nc):
            continue
        foe = board[nr][nc]
        if foe == EMPTY or foe == KING:
            continue
        foe_is_att = is_attacker(foe)
        mover_is_att = mover_side == ATTACKER
        if foe_is_att == mover_is_att:
            continue  # 同阵营不吃
        if in_bounds(br, bc):
            back = board[br][bc]
            back_ok = (back != EMPTY and (is_attacker(back) != foe_is_att)
                       and back != KING)
            if not back_ok and hostile_square(br, bc, foe) and board[br][bc] == EMPTY:
                back_ok = True
            if back_ok:
                caps.append((nr, nc))
        # 棋盘边沿不算颚（简化规则）
    return caps


def king_captured(board, kr, kc):
    """国王是否四面被围（王座/角落空位可作一面）。

    简化：国王在王座上时，三面敌子 + 王座本身作第四面不算，
    这里统一要求四面均为敌子或敌对空格。
    """
    for dr, dc in DIRS:
        nr, nc = kr + dr, kc + dc
        if not in_bounds(nr, nc):
            return False  # 贴边不算被围（国王在边上时）
        p = board[nr][nc]
        if p == ATTACKER:
            continue
        if p == EMPTY and hostile_square(nr, nc, KING):
            continue
        return False
    return True


def apply_move(game, move):
    """执行走法 ((fr,fc),(tr,tc))，返回 (吃子数, 终局结果).

    终局结果: None / "attackers" / "defenders" / "draw".
    非法走法抛 ValueError。
    """
    (fr, fc), (tr, tc) = move
    board = game["board"]
    side = game["turn"]
    if not in_bounds(fr, fc) or not in_bounds(tr, tc):
        raise ValueError(f"越界: {move}")
    piece = board[fr][fc]
    if piece == EMPTY:
        raise ValueError(f"起点无子: {move}")
    if side == ATTACKER and not is_attacker(piece):
        raise ValueError(f"攻方回合不能走守方子: {move}")
    if side != ATTACKER and not is_defender_side(piece):
        raise ValueError(f"守方回合不能走攻方子: {move}")
    if board[tr][tc] != EMPTY:
        raise ValueError(f"落点被占: {move}")
    if (tr, tc) not in rook_targets(board, fr, fc):
        raise ValueError(f"非车式走法或路径被挡: {move}")

    board[fr][fc] = EMPTY
    board[tr][tc] = piece
    if piece == KING:
        game["king_pos"] = (tr, tc)
    game["half"] += 1

    # 国王到达角落 -> 守方胜
    if piece == KING and (tr, tc) in CORNERS:
        return 0, "defenders"

    captured = 0
    for cr, cc in _capture_after(board, tr, tc, side):
        board[cr][cc] = EMPTY
        captured += 1

    # 国王被四面包围 -> 攻方胜（国王不参与普通夹吃，只判包围）
    kr, kc = game["king_pos"]
    if board[kr][kc] == KING and king_captured(board, kr, kc):
        return captured, "attackers"

    # 一方无子可走判负
    nxt = DEFENDER if side == ATTACKER else ATTACKER
    if not legal_moves(game, nxt):
        winner = "defenders" if nxt == ATTACKER else "attackers"
        return captured, winner

    # 重复局面判和
    key = (tuple(tuple(row) for row in board), nxt)
    game["seen"][key] = game["seen"].get(key, 0) + 1
    if game["seen"][key] >= 3:
        return captured, "draw"
    if game["half"] >= MAX_HALF_MOVES:
        return captured, "draw"

    game["turn"] = nxt
    return captured, None


def king_escape_distance(game):
    """国王到最近角落的曼哈顿距离（AI 启发用）。"""
    kr, kc = game["king_pos"]
    return min(abs(kr - cr) + abs(kc - cc) for cr, cc in CORNERS)


def ai_choose(game, rng):
    """贪心 AI: 攻方压缩国王空间+吃子；守方送王逃跑+吃子。"""
    side = game["turn"]
    moves = legal_moves(game, side)
    if not moves:
        return None
    board = game["board"]
    atk_count = sum(row.count(ATTACKER) for row in board)
    dfn_count = sum(row.count(DEFENDER) for row in board)
    kr0, kc0 = game["king_pos"]
    king_mob_before = len(rook_targets(board, kr0, kc0))

    best, best_key = None, None
    for mv in moves:
        g2 = {"board": copy.deepcopy(board), "turn": side,
              "half": game["half"], "king_pos": game["king_pos"], "seen": {}}
        try:
            captured, result = apply_move(g2, mv)
        except ValueError:
            continue
        if result == "attackers":
            key = (10000, 0) if side == ATTACKER else (-10000, 0)
        elif result == "defenders":
            key = (10000, 0) if side != ATTACKER else (-10000, 0)
        elif result == "draw":
            key = (0, 0)
        else:
            b2 = g2["board"]
            a2 = sum(row.count(ATTACKER) for row in b2)
            d2 = sum(row.count(DEFENDER) for row in b2)
            if side == ATTACKER:
                # 吃子 + 压缩国王逃跑距离 + 封堵：王下一步能到角落则重罚
                kr, kc = g2["king_pos"]
                threat = 0
                kmob = 0
                for t in rook_targets(g2["board"], kr, kc):
                    kmob += 1
                    if t in CORNERS:
                        threat = 1
                score = (captured * 50 + (a2 - atk_count) * 10
                         + king_escape_distance(g2) * 2
                         + (king_mob_before - kmob) * 3
                         - threat * 5000)
            else:
                # 吃子 + 国王接近角落
                score = (captured * 50 + (d2 - dfn_count) * 10
                         - king_escape_distance(g2) * 4)
            key = (score, rng.random())
        if best_key is None or key > best_key:
            best_key, best = key, mv
    return best


def play_auto(games=10, seed=42, verbose=False):
    rng = random.Random(seed)
    tally = {"attackers": 0, "defenders": 0, "draw": 0}
    for i in range(games):
        game = new_game()
        result = None
        while result is None:
            mv = ai_choose(game, rng)
            if mv is None:
                result = "defenders" if game["turn"] == ATTACKER else "attackers"
                break
            _, result = apply_move(game, mv)
        tally[result] += 1
        if verbose:
            w = {"attackers": "攻方胜", "defenders": "守方胜", "draw": "和棋"}[result]
            print(f"第 {i+1}/{games} 局: {w}（{game['half']} 半回合）")
    return tally


GLYPH = {EMPTY: "·", ATTACKER: "●", DEFENDER: "○", KING: "♔"}


def render(game):
    board = game["board"]
    lines = ["   " + " ".join(f"{c:2d}" for c in range(SIZE))]
    for r in range(SIZE):
        lines.append(f"{r:2d} " + " ".join(f" {GLYPH[board[r][c]]}" for c in range(SIZE)))
    turn = "攻方(●)" if game["turn"] == ATTACKER else "守方(○)"
    lines.append(f"轮次: {turn}  半回合: {game['half']}")
    return "\n".join(lines)


def parse_coord(s):
    try:
        r, c = s.split(",")
        r, c = int(r), int(c)
    except ValueError:
        raise ValueError("坐标格式应为 行,列，如 5,3")
    if not in_bounds(r, c):
        raise ValueError("坐标越界")
    return r, c


def play_interactive():
    if not sys.stdin.isatty():
        print("交互模式需要终端；无头演示请用 --auto", file=sys.stderr)
        sys.exit(2)
    game = new_game()
    print("Hnefatafl-lite：攻方(●)先手。输入如 3,5>3,8 走子，q 退出。")
    while True:
        print(render(game))
        side = "攻方" if game["turn"] == ATTACKER else "守方"
        try:
            s = input(f"{side}走 > ").strip()
        except EOFError:
            break
        if s.lower() in ("q", "quit", "退出"):
            break
        try:
            a, b = s.split(">")
            mv = (parse_coord(a), parse_coord(b))
            _, result = apply_move(game, mv)
        except ValueError as e:
            print(f"非法走法: {e}")
            continue
        if result:
            print(render(game))
            print({"attackers": "攻方获胜！", "defenders": "国王逃脱，守方获胜！",
                   "draw": "和棋。"}[result])
            break


def main(argv=None):
    ap = argparse.ArgumentParser(description="Hnefatafl-lite：简化版 11x11 维京棋")
    ap.add_argument("--auto", action="store_true", help="AI 对 AI 自动演示")
    ap.add_argument("--games", type=int, default=10, help="自动演示局数")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--verbose", action="store_true", help="打印每局结果")
    args = ap.parse_args(argv)
    if args.auto:
        tally = play_auto(args.games, args.seed, args.verbose)
        print(f"总计: 攻方胜 {tally['attackers']}，守方胜 {tally['defenders']}，"
              f"和棋 {tally['draw']}")
    else:
        play_interactive()


if __name__ == "__main__":
    main()
