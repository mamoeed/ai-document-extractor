import json

from pydantic import BaseModel

from po_extractor.cli import main
from po_extractor.llm.prompts import SCHEMA_TEMPLATE, SYSTEM_PROMPT
from po_extractor.schemas import ExtractedOrder

from .conftest import CUSTOMER_MASTER, ITEM_MASTER


def _model_keys(model: type[BaseModel]) -> dict:
    keys = {}
    for name, field in model.model_fields.items():
        annotation = field.annotation
        args = getattr(annotation, "__args__", ())
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            keys[name] = _model_keys(annotation)
        elif args and isinstance(args[0], type) and issubclass(args[0], BaseModel):  # list[LineItem]
            keys[name] = [_model_keys(args[0])]
        else:
            keys[name] = None
    return keys


def _template_keys(value):
    if isinstance(value, dict):
        return {k: _template_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_template_keys(value[0])]
    return None


def test_prompt_schema_matches_pydantic_model():
    assert _template_keys(json.loads(SCHEMA_TEMPLATE)) == _model_keys(ExtractedOrder)


def test_system_prompt_rules():
    for phrase in [
        "Aurora Parts",
        "ISSUED the PO",
        "Supplier number",
        "Customer no.",
        "Your item no.",
        "Drawing no.",
        "1.118,00",
        "YYYY-MM-DD",
        "field_confidence",
        "ONLY the JSON object",
    ]:
        assert phrase in SYSTEM_PROMPT, phrase


def test_cli_prints_result(tmp_path, capsys, monkeypatch, fake_vlm):
    fake_vlm()
    monkeypatch.setenv("DEEPINFRA_API_KEY", "test-key")
    monkeypatch.setenv("VLM_MODEL", "m")
    path = tmp_path / "order.txt"
    path.write_text("x")
    code = main([str(path), "--customer-master", str(CUSTOMER_MASTER), "--item-master", str(ITEM_MASTER),
                 "--pretty", "--env-file", str(tmp_path / "none.env")])
    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ERROR"
    assert output["issues"][0]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_cli_config_error_exit_code(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
    code = main([str(tmp_path / "x.pdf"), "--customer-master", str(CUSTOMER_MASTER), "--item-master",
                 str(ITEM_MASTER), "--env-file", str(tmp_path / "none.env")])
    assert code == 2
    assert "DEEPINFRA_API_KEY" in capsys.readouterr().err
