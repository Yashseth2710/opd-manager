"""Files on a patient's record: added by whoever has the paper, read by
anyone at the clinic who reads records, and taken off only by whoever put
them there or the clinic admin."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.main import app as application
from app.schemas.document import MAX_BYTES
from tests.api.test_clinic import AUTH, invite_and_accept, sign_up
from tests.api.test_consultations import become, finished, saved
from tests.api.test_lab import in_the_room, ordered
from tests.api.test_patients import register
from tests.api.test_queue import refusal, today
from tests.conftest import FakeRedis, FakeStore, Outbox

API = "/api/v1"


def pdf(marker: str = "") -> bytes:
    """A PDF header and enough after it to be a file. The marker keeps two
    of them from being the same file."""
    return b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n" + (marker or uuid.uuid4().hex).encode()


def jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + uuid.uuid4().bytes


def png() -> bytes:
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + uuid.uuid4().bytes


def webp() -> bytes:
    return b"RIFF\x24\x00\x00\x00WEBPVP8 " + uuid.uuid4().bytes


def heic() -> bytes:
    return b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00" + uuid.uuid4().bytes


async def send(
    client: AsyncClient,
    patient_id: str,
    content: bytes,
    *,
    name: str = "CBC_report.pdf",
    category: str = "lab_report",
    declared: str = "application/pdf",
    **params: Any,
) -> Response:
    return await client.post(
        f"{API}/patients/{patient_id}/documents",
        params={"name": name, "category": category, **params},
        content=content,
        headers={"content-type": declared},
    )


async def sent(
    client: AsyncClient, patient_id: str, content: bytes | None = None, **params: Any
) -> dict[str, Any]:
    response = await send(client, patient_id, content or pdf(), **params)
    assert response.status_code == 201, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def documents(client: AsyncClient, patient_id: str, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/patients/{patient_id}/documents", params=params)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def the_file(client: AsyncClient, document_id: str, **params: Any) -> Response:
    return await client.get(f"{API}/documents/{document_id}/file", params=params)


async def change(client: AsyncClient, document_id: str, **body: Any) -> Response:
    return await client.patch(f"{API}/documents/{document_id}", json=body)


async def a_patient(client: AsyncClient, **details: Any) -> dict[str, Any]:
    await sign_up(client)
    return await register(client, **details)


class TestAdding:
    async def test_a_pdf_goes_on_the_record_and_comes_back_as_it_went_in(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)
        content = pdf()

        found = await sent(client, patient["id"], content)

        assert found["title"] == "CBC report"
        assert found["original_name"] == "CBC_report.pdf"
        assert found["category"] == "lab_report"
        assert found["content_type"] == "application/pdf"
        assert found["size_bytes"] == len(content)
        assert found["uploaded_by"] == "Priya Nair"
        assert found["dated"] is None
        assert found["can_change"] is True
        assert (found["consultation_id"], found["lab_order_id"]) == (None, None)
        # Kept under a generated name, never the one it was sent with.
        [url] = store.files
        assert "CBC" not in url and url.endswith(".pdf")
        assert url.split("/")[-2] == patient["id"]

        shown = await the_file(client, found["id"])
        assert shown.status_code == 200
        assert shown.content == content
        assert shown.headers["content-type"] == "application/pdf"
        assert shown.headers["content-disposition"].startswith(
            'inline; filename="CBC report.pdf"'
        )
        assert shown.headers["x-content-type-options"] == "nosniff"
        assert shown.headers["cache-control"] == "private, no-store"
        # Nothing in the answer points at the store.
        assert "store.test" not in str(found) and "store.test" not in str(shown.headers)

        saved = await the_file(client, found["id"], download="true")
        assert saved.headers["content-disposition"].startswith("attachment;")

    @pytest.mark.parametrize(
        ("content", "kind", "extension"),
        [
            (jpeg(), "image/jpeg", "jpg"),
            (png(), "image/png", "png"),
            (webp(), "image/webp", "webp"),
        ],
    )
    async def test_photos_are_taken_in_the_three_kinds_every_browser_shows(
        self, client: AsyncClient, store: FakeStore, content: bytes, kind: str, extension: str
    ) -> None:
        patient = await a_patient(client)

        found = await sent(
            client, patient["id"], content, name=f"xray.{extension}", category="scan"
        )

        assert found["content_type"] == kind
        shown = await the_file(client, found["id"])
        assert shown.headers["content-type"] == kind
        assert f'filename="xray.{extension}"' in shown.headers["content-disposition"]

    async def test_what_the_file_is_comes_from_its_bytes_not_its_name(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)

        # A photo called a PDF and sent as one is still a photo.
        found = await sent(client, patient["id"], png(), name="scan.pdf")

        assert found["content_type"] == "image/png"
        shown = await the_file(client, found["id"])
        assert shown.headers["content-type"] == "image/png"
        assert 'filename="scan.png"' in shown.headers["content-disposition"]

    @pytest.mark.parametrize(
        ("content", "name", "declared"),
        [
            (b"<html><script>alert(1)</script></html>", "report.pdf", "application/pdf"),
            (
                b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
                "x.svg",
                "image/svg+xml",
            ),
            (b"GIF89a" + b"\x00" * 20, "moving.gif", "image/gif"),
            (b"PK\x03\x04" + b"\x00" * 20, "notes.docx", "application/zip"),
            (pdf(), "invoice.exe", "application/pdf"),
            (b"MZ\x90\x00" + b"\x00" * 20, "report.pdf", "application/pdf"),
        ],
        ids=["html-called-pdf", "svg", "gif", "word", "exe-name", "exe-called-pdf"],
    )
    async def test_anything_else_is_turned_away_before_it_is_stored(
        self, client: AsyncClient, store: FakeStore, content: bytes, name: str, declared: str
    ) -> None:
        patient = await a_patient(client)

        refused = refusal(
            await send(client, patient["id"], content, name=name, declared=declared)
        )

        assert (refused["status"], refused["code"]) == (415, "FILE_UNSUPPORTED_TYPE")
        assert store.puts == 0
        assert (await documents(client, patient["id"]))["total"] == 0

    async def test_an_iphone_photo_is_refused_with_what_to_do_instead(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)

        refused = refusal(
            await send(
                client, patient["id"], heic(), name="IMG_2231.HEIC", declared="image/heic"
            )
        )

        assert refused["code"] == "FILE_UNSUPPORTED_TYPE"
        assert "JPEG" in refused["message"]
        assert store.puts == 0

    async def test_an_empty_file_and_one_too_large(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)

        empty = refusal(await send(client, patient["id"], b""))
        assert (empty["status"], empty["fields"]) == (422, {"file": "That file is empty."})

        too_large = refusal(await send(client, patient["id"], pdf() + b"0" * MAX_BYTES))
        assert (too_large["status"], too_large["code"]) == (413, "FILE_TOO_LARGE")

        # Right at the limit is fine.
        head = pdf()
        exactly = await send(client, patient["id"], head + b"0" * (MAX_BYTES - len(head)))
        assert exactly.status_code == 201, exactly.text
        assert exactly.json()["data"]["size_bytes"] == MAX_BYTES
        assert store.puts == 1

    async def test_the_name_it_came_with_is_tidied_and_can_be_overridden(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)

        from_a_path = await sent(
            client, patient["id"], name="C:\\fakepath\\Echo_2024  final.pdf"
        )
        assert from_a_path["original_name"] == "Echo_2024 final.pdf"
        assert from_a_path["title"] == "Echo 2024 final"

        named = await sent(
            client, patient["id"], title="  Thyroid   panel ", name="scan001.pdf"
        )
        assert named["title"] == "Thyroid panel"

        no_extension = await sent(client, patient["id"], name="WhatsApp Image")
        assert no_extension["title"] == "WhatsApp Image"

        unicode = await sent(client, patient["id"], name="रक्त जाँच.pdf")
        shown = await the_file(client, unicode["id"])
        disposition = shown.headers["content-disposition"]
        assert 'filename="' in disposition
        assert "filename*=UTF-8''%E0%A4%B0" in disposition

        refused = refusal(await send(client, patient["id"], pdf(), title="x" * 121))
        assert refused["status"] == 422

    async def test_the_date_on_the_paper(self, client: AsyncClient, store: FakeStore) -> None:
        patient = await a_patient(client)

        found = await sent(client, patient["id"], dated="2024-03-02")
        assert found["dated"] == "2024-03-02"

        tomorrow = (today() + dt.timedelta(days=1)).isoformat()
        refused = refusal(await send(client, patient["id"], pdf(), dated=tomorrow))
        assert refused["fields"] == {"dated": "The date on it cannot be after today."}

        refused = refusal(await send(client, patient["id"], pdf(), dated="1850-01-01"))
        assert refused["fields"] == {"dated": "That date is too far back."}

        assert (await send(client, patient["id"], pdf(), dated="not-a-date")).status_code == 422
        assert store.puts == 1

    async def test_the_same_file_twice_is_caught(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)
        content = pdf("same")
        await sent(client, patient["id"], content, title="Lipid profile March")

        refused = refusal(await send(client, patient["id"], content, name="copy.pdf"))

        assert (refused["status"], refused["code"]) == (409, "DOC_ALREADY_UPLOADED")
        assert "Lipid profile March" in refused["message"]
        # Which one it is, so the page can offer to use it.
        [existing] = refused["candidates"]
        assert existing["title"] == "Lipid profile March"
        assert store.puts == 1

        # The same paper for someone else is a different matter.
        other = await register(client, first_name="Rohan", phone="9820099887")
        assert (await send(client, other["id"], content)).status_code == 201

    async def test_nothing_is_added_to_an_archived_record_or_a_missing_one(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)
        await client.post(f"{API}/patients/{patient['id']}/archive")

        refused = refusal(await send(client, patient["id"], pdf()))
        assert (refused["status"], refused["code"]) == (409, "PATIENT_ARCHIVED")

        missing = refusal(await send(client, str(uuid.uuid4()), pdf()))
        assert (missing["status"], missing["code"]) == (404, "PATIENT_NOT_FOUND")

        assert (
            refusal(await send(client, patient["id"], pdf(), category="xray"))["status"] == 422
        )
        assert store.puts == 0

    async def test_a_store_that_is_down_is_said_so_and_nothing_is_kept(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)
        store.down = True

        refused = refusal(await send(client, patient["id"], pdf()))

        assert (refused["status"], refused["code"]) == (503, "FILE_UPLOAD_FAILED")
        store.down = False
        assert (await documents(client, patient["id"]))["total"] == 0

    async def test_with_no_store_at_all_uploads_are_refused(self, client: AsyncClient) -> None:
        # No double here, and the suite runs with no token: this is what a
        # deployment missing its token does.
        patient = await a_patient(client)

        refused = refusal(await send(client, patient["id"], pdf()))

        assert (refused["status"], refused["code"]) == (503, "FILE_UPLOAD_FAILED")

    async def test_an_upload_cut_off_part_way_is_not_kept(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)
        disconnect = {"type": "http.disconnect"}

        async def cut_off(scope: Any, receive: Any, send: Any) -> None:
            sent_once = False

            async def first_chunk_then_gone() -> dict[str, Any]:
                nonlocal sent_once
                if not sent_once:
                    sent_once = True
                    return {"type": "http.request", "body": pdf()[:8], "more_body": True}
                return disconnect

            await application(scope, first_chunk_then_gone, send)

        transport = ASGITransport(app=cut_off)
        async with AsyncClient(
            transport=transport, base_url="https://testserver", cookies=client.cookies
        ) as cut:
            response = await send(cut, patient["id"], pdf())

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "FILE_UPLOAD_INTERRUPTED"
        assert store.puts == 0

    async def test_uploads_are_limited_per_person(
        self, client: AsyncClient, store: FakeStore, fake_redis: FakeRedis
    ) -> None:
        patient = await a_patient(client)
        me = (await client.get(f"{AUTH}/me")).json()["data"]["user"]["id"]
        fake_redis.values[f"opd:rl:upload:{me}"] = "59"

        assert (await send(client, patient["id"], pdf())).status_code == 201
        refused = await send(client, patient["id"], pdf())

        assert refused.status_code == 429
        assert int(refused.headers["retry-after"]) > 0
        assert store.puts == 1


class TestLinking:
    async def test_a_file_from_a_visit_carries_its_date(
        self, client: AsyncClient, store: FakeStore, outbox: Outbox
    ) -> None:
        _, patient, notes = await in_the_room(client, outbox)

        found = await sent(
            client, patient["id"], category="referral", consultation_id=notes["id"]
        )

        assert found["consultation_id"] == notes["id"]
        assert found["visit_date"] == today().isoformat()
        await sent(client, patient["id"], category="other")
        from_visit = await documents(client, patient["id"], consultation_id=notes["id"])
        assert [each["id"] for each in from_visit["items"]] == [found["id"]]

    async def test_a_lab_report_file_sits_with_its_order(
        self, client: AsyncClient, store: FakeStore, outbox: Outbox
    ) -> None:
        _, patient, notes = await in_the_room(client, outbox)
        test = await ordered(client, notes, test_code="cbc")

        found = await sent(client, patient["id"], lab_order_id=test["id"])

        assert found["lab_order_id"] == test["id"]
        assert found["lab_order_number"] == "LAB-000001"
        assert found["lab_test_name"] == "Complete blood count"
        # The order's visit, without having to say it.
        assert found["consultation_id"] == notes["id"]
        attached = await documents(client, patient["id"], lab_order_id=test["id"])
        assert attached["total"] == 1

        # A report is filed as one, and cannot be moved out of it.
        refused = refusal(
            await send(client, patient["id"], pdf(), category="scan", lab_order_id=test["id"])
        )
        assert refused["fields"] == {"category": "A lab's report is filed as a lab report."}
        refused = refusal(await change(client, found["id"], category="scan"))
        assert refused["status"] == 422
        assert store.puts == 1

    async def test_a_link_to_someone_elses_visit_or_test_is_refused(
        self, client: AsyncClient, store: FakeStore, outbox: Outbox
    ) -> None:
        _, patient, notes = await in_the_room(client, outbox)
        test = await ordered(client, notes, test_code="tsh")
        other = await register(client, first_name="Rohan", phone="9820099887")

        wrong_visit = refusal(
            await send(client, other["id"], pdf(), consultation_id=notes["id"])
        )
        assert wrong_visit["fields"] == {"consultation_id": "That visit is not this patient's."}

        wrong_test = refusal(await send(client, other["id"], pdf(), lab_order_id=test["id"]))
        assert wrong_test["fields"] == {"lab_order_id": "That lab order is not this patient's."}

        nowhere = refusal(
            await send(client, patient["id"], pdf(), consultation_id=str(uuid.uuid4()))
        )
        assert nowhere["status"] == 422
        assert store.puts == 0

    async def test_a_cancelled_test_takes_no_report(
        self, client: AsyncClient, store: FakeStore, outbox: Outbox
    ) -> None:
        _, patient, notes = await in_the_room(client, outbox)
        test = await ordered(client, notes, test_code="tsh")
        await finished(client, await saved(client, notes, chief_complaint="Tired all the time"))
        cancelled = await client.post(
            f"{API}/lab-orders/{test['id']}/cancel", json={"reason": "Done elsewhere"}
        )
        assert cancelled.status_code == 200, cancelled.text

        refused = refusal(await send(client, patient["id"], pdf(), lab_order_id=test["id"]))

        assert refused["fields"] == {"lab_order_id": "That test was cancelled."}

    async def test_a_file_outlives_the_order_it_was_added_to(
        self, client: AsyncClient, store: FakeStore, outbox: Outbox
    ) -> None:
        _, patient, notes = await in_the_room(client, outbox)
        test = await ordered(client, notes, test_code="tsh")
        found = await sent(client, patient["id"], lab_order_id=test["id"])

        removed = await client.delete(f"{API}/lab-orders/{test['id']}")
        assert removed.status_code == 200, removed.text

        still = (await client.get(f"{API}/documents/{found['id']}")).json()["data"]
        assert (still["lab_order_id"], still["category"]) == (None, "lab_report")
        assert still["consultation_id"] == notes["id"]


class TestPuttingWithATest:
    async def test_a_file_already_on_the_record_is_put_with_its_test(
        self, client: AsyncClient, store: FakeStore, outbox: Outbox
    ) -> None:
        _, patient, notes = await in_the_room(client, outbox)
        test = await ordered(client, notes, test_code="lipid")
        content = pdf()
        loose = await sent(client, patient["id"], content, category="other", title="From home")

        # Sent again from the test's page, it is caught as the same file.
        refused = refusal(await send(client, patient["id"], content, lab_order_id=test["id"]))
        assert refused["candidates"] == [{"id": loose["id"], "title": "From home"}]

        linked = await change(client, loose["id"], lab_order_id=test["id"])
        assert linked.status_code == 200, linked.text
        now = linked.json()["data"]
        assert (now["lab_order_id"], now["category"]) == (test["id"], "lab_report")
        assert now["consultation_id"] == notes["id"]
        assert now["lab_test_name"] == "Lipid profile"
        attached = await documents(client, patient["id"], lab_order_id=test["id"])
        assert [each["id"] for each in attached["items"]] == [loose["id"]]

        unlinked = (await change(client, loose["id"], lab_order_id=None)).json()["data"]
        assert (unlinked["lab_order_id"], unlinked["category"]) == (None, "lab_report")
        assert store.puts == 1

    async def test_only_to_this_patients_live_tests(
        self, client: AsyncClient, store: FakeStore, outbox: Outbox
    ) -> None:
        _, patient, notes = await in_the_room(client, outbox)
        test = await ordered(client, notes, test_code="tsh")
        other = await register(client, first_name="Rohan", phone="9820099887")
        theirs = await sent(client, other["id"], category="other")

        refused = refusal(await change(client, theirs["id"], lab_order_id=test["id"]))
        assert refused["fields"] == {"lab_order_id": "That lab order is not this patient's."}
        refused = refusal(await change(client, theirs["id"], lab_order_id=str(uuid.uuid4())))
        assert refused["status"] == 422

        mine = await sent(client, patient["id"], category="other")
        await finished(client, await saved(client, notes, chief_complaint="Tired all the time"))
        await client.post(
            f"{API}/lab-orders/{test['id']}/cancel", json={"reason": "Not needed"}
        )
        refused = refusal(await change(client, mine["id"], lab_order_id=test["id"]))
        assert refused["fields"] == {"lab_order_id": "That test was cancelled."}
        # Nothing about it changed on the way.
        still = (await client.get(f"{API}/documents/{mine['id']}")).json()["data"]
        assert (still["category"], still["lab_order_id"]) == ("other", None)


class TestListing:
    async def test_newest_on_the_paper_first_with_counts(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)
        old = await sent(
            client, patient["id"], title="Old echo", category="scan", dated="2023-05-01"
        )
        undated = await sent(client, patient["id"], title="Today's report")
        recent = await sent(
            client,
            patient["id"],
            title="Last month",
            dated=(today() - dt.timedelta(days=30)).isoformat(),
        )
        referral = await sent(client, patient["id"], title="Letter", category="referral")

        page = await documents(client, patient["id"])

        assert [each["title"] for each in page["items"]] == [
            referral["title"],
            undated["title"],
            recent["title"],
            old["title"],
        ]
        assert page["total"] == 4
        assert page["counts"] == {"lab_report": 2, "scan": 1, "referral": 1}

        scans = await documents(client, patient["id"], category="scan")
        assert (scans["total"], scans["items"][0]["id"]) == (1, old["id"])
        # Counts stay whole whatever the list is narrowed to.
        assert scans["counts"] == page["counts"]

        second = await documents(client, patient["id"], limit=3, offset=3)
        assert ([each["id"] for each in second["items"]], second["total"]) == ([old["id"]], 4)

    async def test_an_empty_record_and_bad_filters(self, client: AsyncClient) -> None:
        patient = await a_patient(client)

        page = await documents(client, patient["id"])
        assert page == {"items": [], "total": 0, "counts": {}}

        bad = await client.get(
            f"{API}/patients/{patient['id']}/documents", params={"category": "xray"}
        )
        assert bad.status_code == 422
        big = await client.get(
            f"{API}/patients/{patient['id']}/documents", params={"limit": 101}
        )
        assert big.status_code == 422
        missing = refusal(await client.get(f"{API}/patients/{uuid.uuid4()}/documents"))
        assert missing["code"] == "PATIENT_NOT_FOUND"


class TestChanging:
    async def test_whoever_added_it_can_rename_refile_and_date_it(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)
        found = await sent(client, patient["id"], category="other")

        changed = await change(
            client, found["id"], title=" Chest   X-ray ", category="scan", dated="2025-01-09"
        )
        assert changed.status_code == 200, changed.text
        now = changed.json()["data"]
        assert (now["title"], now["category"], now["dated"]) == (
            "Chest X-ray",
            "scan",
            "2025-01-09",
        )

        cleared = (await change(client, found["id"], dated=None)).json()["data"]
        assert (cleared["dated"], cleared["title"]) == (None, "Chest X-ray")

        assert refusal(await change(client, found["id"], title=""))["status"] == 422
        assert refusal(await change(client, found["id"], title=None))["fields"] == {
            "title": "Give it a name."
        }
        assert refusal(await change(client, found["id"], category=None))["status"] == 422
        tomorrow = (today() + dt.timedelta(days=1)).isoformat()
        assert refusal(await change(client, found["id"], dated=tomorrow))["status"] == 422
        assert refusal(await change(client, found["id"], blob_url="x"))["status"] == 422
        missing = refusal(await change(client, str(uuid.uuid4()), title="x"))
        assert (missing["status"], missing["code"]) == (404, "DOC_NOT_FOUND")

    async def test_only_the_uploader_or_the_admin_changes_or_removes_it(
        self, client: AsyncClient, store: FakeStore, outbox: Outbox
    ) -> None:
        clinic, patient, _ = await in_the_room(client, outbox)
        # The doctor adds one, then the desk adds one.
        doctors = await sent(client, patient["id"], title="From the doctor")
        await become(client, clinic.admin)
        desk = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await become(client, desk)
        desks = await sent(client, patient["id"], title="From the desk")

        listed = {
            each["title"]: each for each in (await documents(client, patient["id"]))["items"]
        }
        assert listed["From the doctor"]["can_change"] is False
        assert listed["From the desk"]["can_change"] is True
        refused = refusal(await change(client, doctors["id"], title="Mine now"))
        assert (refused["status"], refused["code"]) == (403, "DOC_NOT_UPLOADER")
        refused = refusal(await client.delete(f"{API}/documents/{doctors['id']}"))
        assert refused["code"] == "DOC_NOT_UPLOADER"

        await become(client, clinic.admin)
        listed = {
            each["title"]: each for each in (await documents(client, patient["id"]))["items"]
        }
        assert all(each["can_change"] for each in listed.values())
        assert (
            await change(client, desks["id"], title="Filed by the admin")
        ).status_code == 200
        assert (await client.delete(f"{API}/documents/{doctors['id']}")).status_code == 200
        assert len(store.files) == 1

    async def test_read_only_staff_see_files_and_touch_nothing(
        self, client: AsyncClient, store: FakeStore, outbox: Outbox
    ) -> None:
        patient = await a_patient(client)
        found = await sent(client, patient["id"])
        admin = (await client.get(f"{AUTH}/me")).json()["data"]["user"]["email"]
        staff = await invite_and_accept(client, role="staff", outbox=outbox)
        await become(client, staff)

        page = await documents(client, patient["id"])
        assert page["items"][0]["can_change"] is False
        assert (await the_file(client, found["id"])).status_code == 200

        assert refusal(await send(client, patient["id"], pdf()))["status"] == 403
        assert refusal(await change(client, found["id"], title="x"))["status"] == 403
        assert refusal(await client.delete(f"{API}/documents/{found['id']}"))["status"] == 403
        await become(client, admin)
        assert len(store.files) == 1


class TestRemoving:
    async def test_the_row_and_the_file_both_go(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)
        found = await sent(client, patient["id"])
        kept = await sent(client, patient["id"])

        removed = await client.delete(f"{API}/documents/{found['id']}")

        assert removed.status_code == 200, removed.text
        assert removed.json()["data"] == {"removed": True}
        assert len(store.files) == 1
        assert refusal(await the_file(client, found["id"]))["code"] == "DOC_NOT_FOUND"
        assert refusal(await client.get(f"{API}/documents/{found['id']}"))["status"] == 404
        assert [each["id"] for each in (await documents(client, patient["id"]))["items"]] == [
            kept["id"]
        ]
        again = refusal(await client.delete(f"{API}/documents/{found['id']}"))
        assert again["status"] == 404

    async def test_a_store_that_is_down_leaves_the_file_listed(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)
        found = await sent(client, patient["id"])
        store.down = True

        refused = refusal(await client.delete(f"{API}/documents/{found['id']}"))

        assert (refused["status"], refused["code"]) == (503, "FILE_UPLOAD_FAILED")
        store.down = False
        assert (await documents(client, patient["id"]))["total"] == 1
        assert len(store.files) == 1

    async def test_a_file_gone_from_the_store_says_so(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)
        found = await sent(client, patient["id"])
        store.files.clear()

        refused = refusal(await the_file(client, found["id"]))

        assert (refused["status"], refused["code"]) == (404, "FILE_MISSING")
        # It can still be taken off the record.
        assert (await client.delete(f"{API}/documents/{found['id']}")).status_code == 200


class TestBoundaries:
    async def test_another_clinic_finds_nothing(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)
        found = await sent(client, patient["id"])
        await client.post(f"{AUTH}/logout")
        await sign_up(client, clinic_name="Other Clinic")

        assert (
            refusal(await client.get(f"{API}/patients/{patient['id']}/documents"))["status"]
            == 404
        )
        assert refusal(await client.get(f"{API}/documents/{found['id']}"))["status"] == 404
        assert refusal(await the_file(client, found["id"]))["status"] == 404
        assert refusal(await change(client, found["id"], title="Mine"))["status"] == 404
        assert refusal(await client.delete(f"{API}/documents/{found['id']}"))["status"] == 404
        assert refusal(await send(client, patient["id"], pdf()))["status"] == 404
        assert len(store.files) == 1

    async def test_signed_out_is_turned_away(
        self, client: AsyncClient, store: FakeStore
    ) -> None:
        patient = await a_patient(client)
        found = await sent(client, patient["id"])
        await client.post(f"{AUTH}/logout")

        assert (await the_file(client, found["id"])).status_code == 401
        assert (await send(client, patient["id"], pdf())).status_code == 401
        assert (
            await client.get(f"{API}/patients/{patient['id']}/documents")
        ).status_code == 401
