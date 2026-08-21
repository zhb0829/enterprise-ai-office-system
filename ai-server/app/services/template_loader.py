"""种子模板与文风配置加载，及模板 JSON Schema 校验。"""
import json
import logging
from pathlib import Path

from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from ..models import StyleConfig, Template

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TEMPLATES_DIR = DATA_DIR / "templates"

# 模板结构 JSON Schema（draft 2020-12）
TEMPLATE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "name",
        "title",
        "category",
        "output_format",
        "tone_guidelines",
        "sections",
        "placeholders",
    ],
    "properties": {
        "name": {"type": "string", "minLength": 1, "pattern": "^[a-zA-Z0-9_]+$"},
        "title": {"type": "string", "minLength": 1},
        "category": {"type": "string", "minLength": 1},
        "output_format": {"type": "string", "enum": ["markdown", "text"]},
        "tone_guidelines": {"type": "string"},
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["key", "name", "required"],
                "properties": {
                    "key": {"type": "string", "minLength": 1},
                    "name": {"type": "string", "minLength": 1},
                    "required": {"type": "boolean"},
                    "hint": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "placeholders": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["key", "name", "required", "source"],
                "properties": {
                    "key": {"type": "string", "minLength": 1},
                    "name": {"type": "string", "minLength": 1},
                    "required": {"type": "boolean"},
                    # source 取值：eventDesc / audience / people / keyFactsAny / title，或 keyFacts:<要素名>
                    "source": {
                        "type": "string",
                        "pattern": "^(eventDesc|audience|people|keyFactsAny|title|keyFacts:.+)$",
                    },
                    "hint": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}

TEMPLATE_VALIDATOR = Draft202012Validator(TEMPLATE_SCHEMA)


def validate_template(data: dict) -> list[str]:
    """校验模板结构，返回错误信息列表；空列表表示校验通过。

    覆盖：JSON Schema 结构校验 + 业务规则（key 唯一性）。
    """
    errors: list[str] = []
    for err in sorted(TEMPLATE_VALIDATOR.iter_errors(data), key=lambda e: list(e.absolute_path)):
        loc = ".".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{loc}: {err.message}")

    if isinstance(data.get("sections"), list):
        keys = [s.get("key") for s in data["sections"]]
        if len(keys) != len(set(keys)):
            errors.append("sections.key 存在重复")

    if isinstance(data.get("placeholders"), list):
        keys = [p.get("key") for p in data["placeholders"]]
        if len(keys) != len(set(keys)):
            errors.append("placeholders.key 存在重复")

    return errors


def load_styles(db: Session | None = None) -> dict:
    """读取文风配置（styles 数组 + channel_style_map）。

    优先读 style_config 表；库中无配置时用 styles.json 种子初始化入库；
    传入 db 为 None 时回退到文件读取（兼容启动前等无会话场景）。
    """
    if db is not None:
        row = db.query(StyleConfig).filter(StyleConfig.config_key == "styles").first()
        if row and row.value:
            return row.value
        # 无则从文件种子初始化
        seed = _load_styles_file()
        _save_styles(db, seed)
        return seed
    return _load_styles_file()


def _load_styles_file() -> dict:
    with open(DATA_DIR / "styles.json", encoding="utf-8") as f:
        return json.load(f)


def save_styles(db: Session, data: dict) -> dict:
    """保存文风配置（校验结构后覆盖写库）。"""
    data = dict(data)
    styles = data.get("styles") or []
    if not isinstance(styles, list) or not styles:
        raise ValueError("文风列表不能为空")
    if not isinstance(data.get("channel_style_map"), dict):
        data["channel_style_map"] = {}
    keys = [s.get("key") for s in styles if isinstance(s, dict) and s.get("key")]
    if len(keys) != len(set(keys)):
        raise ValueError("文风 key 存在重复")
    _save_styles(db, data)
    return data


def _save_styles(db: Session, data: dict) -> None:
    row = db.query(StyleConfig).filter(StyleConfig.config_key == "styles").first()
    if row:
        row.value = data
    else:
        db.add(StyleConfig(config_key="styles", value=data))
    db.commit()


def load_seed_templates(db: Session) -> int:
    """将 data/templates/*.json 作为内置模板 upsert 到数据库，返回处理数量。

    校验失败的内置模板会告警并跳过（保留库中已有数据）；内置模板随应用版本更新覆盖，
    企业自定义模板（is_builtin=False）不受影响。
    """
    count = 0
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            tpl = json.load(f)
        errs = validate_template(tpl)
        if errs:
            logger.warning("模板 %s 校验失败，跳过：%s", path.name, "; ".join(errs))
            continue
        existing = db.query(Template).filter(Template.name == tpl["name"]).first()
        if existing:
            if existing.is_builtin:
                existing.category = tpl.get("category", existing.category)
                existing.schema_ = tpl
        else:
            db.add(
                Template(
                    name=tpl["name"],
                    category=tpl.get("category", ""),
                    schema_=tpl,
                    is_builtin=True,
                    is_active=True,
                )
            )
        count += 1
    db.commit()
    return count