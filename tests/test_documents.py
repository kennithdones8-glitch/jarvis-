"""Documents: real PDF and .docx files generated here, read through the real tool and gateway."""

import io
import json
import zipfile

import pytest

from model_servers import start_ollama

from jarvis.cli import main as cli_main
from jarvis.core import TaskState
from jarvis.core.permissions import Policy
from jarvis.core.tools import ApprovalRequired, PermissionDenied, ToolError
from jarvis.orchestrator import Orchestrator
from jarvis.tools import default_registry
from jarvis.tools.documents import parse_pages
from jarvis.tools.fs import FileTool


def make_pdf(pages: list[str]) -> bytes:
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * i} 0 R' for i in range(len(pages)))}] /Count {len(pages)} >>".encode(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, text in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {5 + 2 * i} 0 R >>".encode())
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def make_docx(paragraphs: list[tuple[str, str | None]], table: list[list[str]] | None = None) -> bytes:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = ""
    for text, style in paragraphs:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        body += f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"
    if table:
        body += "<w:tbl>" + "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row)
                                    + "</w:tr>" for row in table) + "</w:tbl>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


@pytest.fixture
def k(make_kernel, tmp_path):
    return make_kernel(registry="default")  # the real production tools (with move's destination guard)


def test_pdf_pages_and_ranges(k, root):
    (root / "report.pdf").write_bytes(make_pdf(["Quarterly revenue rose 12 percent", "Costs fell", "Outlook stable"]))
    r = k.gateway.invoke("doc", "read", {"path": f"{root}/report.pdf"})
    assert r["format"] == "pdf" and r["pages_total"] == 3 and r["untrusted"]
    assert "--- Page 1 ---\nQuarterly revenue rose 12 percent" in r["content"] and "Outlook stable" in r["content"]
    r2 = k.gateway.invoke("doc", "read", {"path": f"{root}/report.pdf", "pages": "2-3"})
    assert r2["pages_read"] == [2, 3] and "Quarterly" not in r2["content"] and r2["truncated"]
    info = k.gateway.invoke("doc", "info", {"path": f"{root}/report.pdf"})
    assert "content" not in info and info["words"] > 5 and info["preview"].startswith("--- Page 1")


def test_scanned_encrypted_and_corrupt_pdfs_reported_honestly(k, root):
    (root / "scan.pdf").write_bytes(make_pdf(["", ""]))
    assert "looks scanned" in k.gateway.invoke("doc", "read", {"path": f"{root}/scan.pdf"})["note"]
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(["secret"]))))
    w.encrypt("hunter2")
    with open(root / "locked.pdf", "wb") as fh:
        w.write(fh)
    with pytest.raises(ToolError, match="password-protected"):
        k.gateway.invoke("doc", "read", {"path": f"{root}/locked.pdf"})
    (root / "broken.pdf").write_bytes(b"%PDF-1.4 garbage")
    with pytest.raises(ToolError, match="could not read"):
        k.gateway.invoke("doc", "read", {"path": f"{root}/broken.pdf"})


def test_docx_headings_paragraphs_tables(k, root):
    (root / "plan.docx").write_bytes(make_docx([("Budget plan", "Heading1"), ("Cut dining out by half", None)],
                                               table=[["Item", "Cost"], ["Rent", "1200"]]))
    r = k.gateway.invoke("doc", "read", {"path": f"{root}/plan.docx"})
    assert r["content"].splitlines() == ["## Budget plan", "Cut dining out by half", "| Item | Cost |", "| Rent | 1200 |"]
    (root / "old.docx").write_bytes(b"not a zip")
    with pytest.raises(ToolError, match="old .doc"):
        k.gateway.invoke("doc", "read", {"path": f"{root}/old.docx"})


def test_text_html_and_unsupported(k, root):
    (root / "a.md").write_text("# Title\nbody")
    (root / "p.html").write_text("<title>T</title><p>Hello <script>x()</script>world</p>")
    (root / "s.xlsx").write_bytes(b"PK")
    assert k.gateway.invoke("doc", "read", {"path": f"{root}/a.md"})["content"] == "# Title\nbody"
    h = k.gateway.invoke("doc", "read", {"path": f"{root}/p.html"})
    assert h["title"] == "T" and "x()" not in h["content"]
    with pytest.raises(ToolError, match="can't read .xlsx"):
        k.gateway.invoke("doc", "read", {"path": f"{root}/s.xlsx"})


def test_documents_outside_approved_folders_denied(k, tmp_path):
    (tmp_path / "private.pdf").write_bytes(make_pdf(["nope"]))
    with pytest.raises(PermissionDenied, match="outside"):
        k.gateway.invoke("doc", "read", {"path": str(tmp_path / "private.pdf")})


def test_parse_pages():
    assert parse_pages("1,3-4", 5) == [0, 2, 3] and parse_pages(None, 2) == [0, 1] and parse_pages(2, 3) == [1]
    for bad in ("0", "3-1", "x", "1;2"):
        with pytest.raises(ToolError):
            parse_pages(bad, 5)


# ---- moving files --------------------------------------------------------------------------
def test_move_needs_approval_shows_destination_and_never_overwrites(k, root):
    (root / "inbox").mkdir()
    (root / "inbox" / "invoice.pdf").write_bytes(b"x")
    args = {"path": f"{root}/inbox/invoice.pdf", "to": f"{root}/notes/Invoices/2026-invoice.pdf"}
    with pytest.raises(ApprovalRequired) as ei:
        k.gateway.invoke("fs", "move", args, task_id="t")
    assert (root / "inbox" / "invoice.pdf").exists()
    k.approvals.decide(ei.value.approval_id, approve=True, by="user:test")
    out = k.gateway.invoke("fs", "move", args, task_id="t")
    assert out["to"].endswith("Invoices/2026-invoice.pdf") and (root / "notes" / "Invoices" / "2026-invoice.pdf").exists()
    (root / "inbox" / "b.txt").write_text("1")
    (root / "notes" / "b.txt").write_text("existing")
    args2 = {"path": f"{root}/inbox/b.txt", "to": f"{root}/notes"}           # into a folder that already has b.txt
    with pytest.raises(ApprovalRequired) as ei2:
        k.gateway.invoke("fs", "move", args2, task_id="t2")
    k.approvals.decide(ei2.value.approval_id, approve=True, by="user:test")
    with pytest.raises(ToolError, match="never overwrites"):
        k.gateway.invoke("fs", "move", args2, task_id="t2")
    assert (root / "notes" / "b.txt").read_text() == "existing"


def test_move_destination_outside_roots_or_protected_refused_even_if_approved(k, root, tmp_path):
    (root / "f.txt").write_text("data")
    for dest in (str(tmp_path / "outside.txt"), str(tmp_path / "home" / "stolen.txt"), f"{root}/../escape.txt"):
        args = {"path": f"{root}/f.txt", "to": dest}
        with pytest.raises(ApprovalRequired) as ei:
            k.gateway.invoke("fs", "move", args, task_id=f"t-{dest}")
        k.approvals.decide(ei.value.approval_id, approve=True, by="user:test")
        with pytest.raises(ToolError, match="destination not allowed"):
            k.gateway.invoke("fs", "move", args, task_id=f"t-{dest}")
    assert (root / "f.txt").read_text() == "data"


def test_move_reconcile(tmp_path):
    src, dest = tmp_path / "a.txt", tmp_path / "b.txt"
    src.write_text("x")
    args = {"path": str(src), "to": str(dest)}
    assert FileTool._reconcile_move(args, "op") == "not_done"
    src.rename(dest)
    assert FileTool._reconcile_move(args, "op") == "done"


# ---- planning & end to end -----------------------------------------------------------------
@pytest.fixture
def orch(make_kernel, tmp_path, root):
    srv = start_ollama(installed=["planner:7b"])
    script = {"plan": None}
    srv.reply = lambda body: (script["plan"] if "planning component" in body["messages"][0]["content"]
                              else "- Revenue up 12%\n- Costs down")
    (tmp_path / "jarvis.toml").write_text(f'[providers.ollama]\nkind = "ollama"\nenabled = true\nhost = "{srv.url}"\n'
        '[[providers.ollama.models]]\nid = "planner:7b"\ncapabilities = ["chat", "plan", "json", "summarize"]\n'
        'context_tokens = 32768\nquality = 3\nspeed = 2\n')
    k = make_kernel(registry="default", config_path=tmp_path / "jarvis.toml")
    yield Orchestrator(k, notes_dir=str(root / "notes")), script, srv
    srv.stop()


def test_planner_sees_file_names_in_mentioned_approved_folders_only(orch, root, tmp_path):
    o, _, _ = orch
    (root / "notes" / "scan_001.pdf").write_bytes(b"x")
    (root / "notes" / ".hidden").write_text("x")
    (tmp_path / "secret-folder").mkdir()
    (tmp_path / "secret-folder" / "passwords.txt").write_text("x")
    ctx = o.planner.folder_context(f"Rename the PDFs in {root}/notes and also look in {tmp_path}/secret-folder")
    assert "scan_001.pdf" in ctx and ".hidden" not in ctx and "passwords.txt" not in ctx


def test_summarise_a_pdf_end_to_end(orch, root):
    o, script, srv = orch
    (root / "report.pdf").write_bytes(make_pdf(["Quarterly revenue rose 12 percent", "Costs fell 3 percent"]))
    script["plan"] = json.dumps({"goal": "Summarise the report", "question": None, "cannot": None, "steps": [
        {"description": "Read the PDF", "tool": "doc", "action": "read", "args": {"path": f"{root}/report.pdf"}, "depends_on": []},
        {"description": "Summarise", "tool": "llm", "action": "compose",
         "args": {"instruction": "Two bullet summary", "inputs": ["{{steps.0.content}}"]}, "depends_on": [0]},
        {"description": "Save", "tool": "fs", "action": "write",
         "args": {"path": f"{root}/notes/report-summary.md", "content": "{{steps.1.text}}"}, "depends_on": [1]}]})
    plan = o.plan(f"Summarise {root}/report.pdf into my notes")
    tid = o.submit("summarise", plan)
    assert o.kernel.engine.run(tid) is TaskState.COMPLETED
    assert (root / "notes" / "report-summary.md").read_text() == "- Revenue up 12%\n- Costs down"
    writer_input = srv.received[-1]["body"]["messages"][1]["content"]
    assert "Quarterly revenue rose 12 percent" in writer_input and "<<<DATA 1>>>" in writer_input


# ---- allow-folder --------------------------------------------------------------------------
def test_allow_folder_command(tmp_path, monkeypatch):
    home = tmp_path / "jhome"
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    assert cli_main(["--home", str(home), "init"]) == 0
    assert cli_main(["--home", str(home), "allow-folder", str(downloads)]) == 0
    import tomllib
    policy = Policy.from_dict(tomllib.loads((home / "policy.toml").read_text()))
    assert downloads.resolve() in policy.roots
    assert cli_main(["--home", str(home), "allow-folder", str(downloads)]) == 0     # idempotent
    assert tomllib.loads((home / "policy.toml").read_text())["filesystem"]["roots"].count(str(downloads.resolve())) == 1
    assert cli_main(["--home", str(home), "allow-folder", str(home)]) == 1           # never its own data folder
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli_main(["--home", str(home), "allow-folder", str(tmp_path)]) == 1       # never the whole home folder
    assert cli_main(["--home", str(home), "allow-folder", str(downloads), "--remove"]) == 0
    policy = Policy.from_dict(tomllib.loads((home / "policy.toml").read_text()))
    assert downloads.resolve() not in policy.roots
