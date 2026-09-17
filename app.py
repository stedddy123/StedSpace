import json
import os
import random
from datetime import datetime

from flask import Flask, render_template, request, jsonify

# === 文件路径 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GAME_DATA_FILE = os.path.join(BASE_DIR, "game_data.json")
PROGRESS_FILE = os.path.join(BASE_DIR, "progress.json")

# 1% 完美结局概率
PERFECT_CHANCE = 0.01
# 每轮循环精神值自动上升量
LOOP_SPIRIT_COST = 20

app = Flask(__name__)


# === 游戏数据加载 ===
def load_game_data():
    """从 JSON 文件加载游戏剧情数据"""
    with open(GAME_DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# === 进度持久化 ===
def load_progress():
    """加载玩家进度，如果不存在则返回 None"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None


def save_progress(progress):
    """保存玩家进度到文件"""
    progress["updated_at"] = datetime.now().isoformat()
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def create_initial_progress(game_data, loop_count=0, stats_override=None):
    """创建初始进度（stats_override 可覆盖属性初始值，用于循环累加精神值）"""
    stats_init = game_data["meta"].get("stats_init", {})
    stats = dict(stats_init)
    if stats_override:
        stats.update(stats_override)
    return {
        "current_node": "start",
        "history": ["start"],
        "stats": stats,
        "loop_count": loop_count,
        "fired_events": [],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "node_log": [
            {"node": "start", "title": game_data["nodes"]["start"]["title"]}
        ],
    }


# === 人像状态判定 ===
PORTRAITS = {
    "good": {"label": "精神饱满", "img": "/static/images/portrait-good.jpg"},
    "normal": {"label": "状态还行", "img": "/static/images/portrait-normal.jpg"},
    "slacking": {"label": "摸鱼中", "img": "/static/images/portrait-slacking.jpg"},
    "exhausted": {"label": "疲惫不堪", "img": "/static/images/portrait-exhausted.jpg"},
    "collapsed": {"label": "心态崩了", "img": "/static/images/portrait-collapsed.jpg"},
}


def evaluate_portrait(stats):
    """根据属性值判定当前人像状态（按优先级从高到低）"""
    work_spirit = stats.get("打工魂", 50)
    slacking = stats.get("摸鱼值", 0)
    beast = stats.get("牛马指数", 0)
    mind = stats.get("精神值", 30)

    if beast >= 40 or work_spirit <= 15 or mind >= 85:
        return PORTRAITS["collapsed"]
    if beast >= 20 or mind >= 60:
        return PORTRAITS["exhausted"]
    if slacking >= 20:
        return PORTRAITS["slacking"]
    if work_spirit >= 65:
        return PORTRAITS["good"]
    return PORTRAITS["normal"]


# === 随机突发事件 ===
def maybe_trigger_event(game_data, progress, node_id, node):
    """按概率从节点事件池中触发一个随机事件，触发后记录并保存"""
    pool = node.get("event_pool", [])
    if not pool:
        return None
    chance = node.get("event_chance", 0.3)
    if random.random() > chance:
        return None

    event_id = random.choice(pool)
    event = game_data["random_events"].get(event_id)
    if not event:
        return None

    fired = progress.setdefault("fired_events", [])
    key = f"{node_id}:{event_id}"
    if key in fired:
        return None

    fired.append(key)
    progress["pending_event"] = {"event": event_id, "return_to": node_id}
    save_progress(progress)
    return event


def resolve_node(game_data, progress):
    """解析当前要展示的节点：若有待处理的随机事件则展示事件节点"""
    node_id = progress["current_node"]

    # 有挂起的事件（玩家正在事件节点中）
    if "pending_event" in progress:
        pe = progress["pending_event"]
        event = game_data["random_events"].get(pe.get("event"))
        if event:
            return event, node_id

    node = game_data["nodes"].get(node_id)
    if not node:
        progress["current_node"] = "start"
        progress.setdefault("history", []).append("start")
        save_progress(progress)
        node = game_data["nodes"]["start"]
        node_id = "start"

    # 尝试触发随机事件
    event = maybe_trigger_event(game_data, progress, node_id, node)
    if event:
        return event, node_id
    return node, node_id


# === 结局判定 ===
def evaluate_ending(game_data, stats):
    """根据属性值判定普通结局"""
    rules = game_data.get("ending_eval", {}).get("rules", [])
    for rule in rules:
        condition = rule.get("condition", {})
        if condition.get("default"):
            return {
                "ending_id": rule["ending"],
                "comment": rule.get("comment", ""),
            }
        stat_name = condition.get("stat")
        op = condition.get("op")
        value = condition.get("value", 0)
        current = stats.get(stat_name, 0)
        if op == ">=" and current >= value:
            return {
                "ending_id": rule["ending"],
                "comment": rule.get("comment", ""),
            }
        if op == "<=" and current <= value:
            return {
                "ending_id": rule["ending"],
                "comment": rule.get("comment", ""),
            }
    if rules:
        last = rules[-1]
        return {"ending_id": last["ending"], "comment": last.get("comment", "")}
    return {"ending_id": "ending_leave", "comment": ""}


def resolve_ending(game_data, progress):
    """结局结算：先 1% 判定完美结局，否则按属性判定普通结局。
    结果写入 progress，保证刷新页面后结局稳定不变。"""
    if "final_ending" not in progress:
        if random.random() < PERFECT_CHANCE:
            progress["final_ending"] = "ending_perfect"
            progress["perfect_done"] = True
            progress["final_comment"] = "你打出了传说中1%的完美结局，成功跳出了周五的循环！"
        else:
            result = evaluate_ending(game_data, progress["stats"])
            progress["final_ending"] = result["ending_id"]
            progress["perfect_done"] = False
            progress["final_comment"] = result.get("comment", "")
        save_progress(progress)

    ending = game_data["endings"].get(progress["final_ending"], {})
    return {
        "ending": {
            "title": ending.get("title", "结局"),
            "text": ending.get("text", ""),
        },
        "comment": progress.get("final_comment", ""),
        "perfect": progress.get("perfect_done", False),
        "game_over": ending.get("game_over", False),
    }


def apply_effects(progress, effects):
    """应用属性变化，精神值不低于 0"""
    for stat, delta in effects.items():
        progress["stats"][stat] = progress["stats"].get(stat, 0) + delta
    if "精神值" in progress["stats"]:
        progress["stats"]["精神值"] = max(0, progress["stats"]["精神值"])


# === 页面路由 ===
@app.route("/")
def home():
    """游戏主页"""
    return render_template("index.html")


# === API 路由 ===
@app.route("/api/state")
def api_state():
    """获取当前游戏状态（进度 + 当前节点内容）"""
    game_data = load_game_data()
    progress = load_progress()

    if progress is None:
        progress = create_initial_progress(game_data)
        save_progress(progress)

    node_id = progress["current_node"]
    meta = game_data["meta"]

    # 结局结算节点
    if node_id == "ending_eval":
        result = resolve_ending(game_data, progress)
        return jsonify({
            "has_save": True,
            "is_ending": True,
            "perfect": result["perfect"],
            "game_over": result["game_over"],
            "ending": result["ending"],
            "comment": result["comment"],
            "stats": progress["stats"],
            "portrait": evaluate_portrait(progress["stats"]),
            "loop_count": progress.get("loop_count", 0),
            "meta": {
                "title": meta["title"],
                "subtitle": meta["subtitle"],
                "loop_setting": meta.get("loop_setting", {}),
            },
        })

    # 解析当前展示节点（可能为随机事件节点）
    node, _ = resolve_node(game_data, progress)
    is_event = "pending_event" in progress

    return jsonify({
        "has_save": True,
        "is_ending": False,
        "is_event": is_event,
        "node": {
            "id": node_id,
            "title": node.get("title") or node.get("name", ""),
            "text": node.get("text", ""),
            "choices": node.get("choices", []),
        },
        "stats": progress["stats"],
        "portrait": evaluate_portrait(progress["stats"]),
        "stat_descriptions": meta.get("stat_descriptions", {}),
        "loop_count": progress.get("loop_count", 0),
        "meta": {
            "title": meta["title"],
            "subtitle": meta["subtitle"],
            "loop_setting": meta.get("loop_setting", {}),
        },
    })


@app.route("/api/choose", methods=["POST"])
def api_choose():
    """玩家做出选择，推进剧情，自动保存进度"""
    game_data = load_game_data()
    progress = load_progress()

    if progress is None:
        progress = create_initial_progress(game_data)

    data = request.get_json()
    if not data or "choice_index" not in data:
        return jsonify({"error": "缺少 choice_index 参数"}), 400

    choice_index = data["choice_index"]

    # === 处理随机事件中的选择 ===
    if "pending_event" in progress:
        pe = progress["pending_event"]
        event = game_data["random_events"].get(pe.get("event"))
        if not event:
            progress.pop("pending_event", None)
            save_progress(progress)
            return jsonify({"error": "事件不存在"}), 400

        choices = event.get("choices", [])
        if choice_index < 0 or choice_index >= len(choices):
            return jsonify({"error": "无效的选择"}), 400
        choice = choices[choice_index]

        # 应用事件属性变化
        effects = choice.get("effects", {})
        apply_effects(progress, effects)

        # 记录事件选择
        progress.setdefault("node_log", []).append(
            {"node": "event", "choice_text": choice.get("text", ""), "title": event.get("name", "突发事件")}
        )

        # 事件后续跳转：RETURN 返回原剧情节点
        next_node = choice.get("next", "RETURN")
        if next_node == "RETURN":
            next_node = pe.get("return_to", "start")
        progress["current_node"] = next_node
        progress["history"].append(next_node)
        progress.pop("pending_event", None)
        save_progress(progress)

        # 返回新节点（可能是结局）
        return _resolve_choose_response(progress, effects, choice.get("text", ""))

    # === 正常剧情选择 ===
    node_id = progress["current_node"]
    node = game_data["nodes"].get(node_id)
    if not node:
        return jsonify({"error": "当前节点不存在"}), 400

    choices = node.get("choices", [])
    if choice_index < 0 or choice_index >= len(choices):
        return jsonify({"error": "无效的选择"}), 400

    choice = choices[choice_index]

    # 应用属性变化
    effects = choice.get("effects", {})
    apply_effects(progress, effects)

    # 前进到下一个节点
    next_node = choice.get("next", "start")
    progress["current_node"] = next_node
    progress["history"].append(next_node)

    # 记录节点日志
    log_entry = {"node": next_node, "choice_text": choice.get("text", "")}
    if next_node in game_data["nodes"]:
        log_entry["title"] = game_data["nodes"][next_node].get("title", "")
    progress.setdefault("node_log", []).append(log_entry)

    save_progress(progress)

    return _resolve_choose_response(progress, effects, choice.get("text", ""))


def _resolve_choose_response(progress, effects, choice_text):
    """根据 progress 当前节点构造响应"""
    game_data = load_game_data()
    node_id = progress["current_node"]

    if node_id == "ending_eval":
        result = resolve_ending(game_data, progress)
        return jsonify({
            "is_ending": True,
            "perfect": result["perfect"],
            "game_over": result["game_over"],
            "ending": result["ending"],
            "comment": result["comment"],
            "stats": progress["stats"],
            "portrait": evaluate_portrait(progress["stats"]),
            "effects": effects,
            "choice_text": choice_text,
            "loop_count": progress.get("loop_count", 0),
        })

    node, _ = resolve_node(game_data, progress)
    return jsonify({
        "is_ending": False,
        "node": {
            "id": node_id,
            "title": node.get("title") or node.get("name", ""),
            "text": node.get("text", ""),
            "choices": node.get("choices", []),
        },
        "stats": progress["stats"],
        "portrait": evaluate_portrait(progress["stats"]),
        "effects": effects,
        "choice_text": choice_text,
        "loop_count": progress.get("loop_count", 0),
    })


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """重置游戏进度：
    mode=loop  进入下一轮循环（循环次数 +1，精神值自动上升）
    mode=fresh 全新开始（循环次数归零，精神值回到初始）"""
    game_data = load_game_data()
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "loop")
    old = load_progress()
    loop_count = 0
    stats_override = None
    if mode == "loop" and old:
        loop_count = old.get("loop_count", 0) + 1
        # 循环侵蚀：精神值继承并上升，其余属性全部重置为初始值
        stats_override = {"精神值": old.get("stats", {}).get("精神值", 30) + LOOP_SPIRIT_COST}

    progress = create_initial_progress(game_data, loop_count=loop_count, stats_override=stats_override)
    save_progress(progress)
    return jsonify({
        "success": True,
        "message": "进度已重置",
        "loop_count": loop_count,
        "spirit_added": LOOP_SPIRIT_COST if mode == "loop" and old else 0,
        "stats": progress["stats"],
    })


@app.route("/api/progress")
def api_progress():
    """获取原始进度文件内容（用于查看存档详情）"""
    progress = load_progress()
    if progress is None:
        return jsonify({"has_save": False})
    return jsonify({"has_save": True, "progress": progress})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)