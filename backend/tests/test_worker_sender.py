from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select

from server_api.db import BetAttempt, BetOrder, StrategyEvent, WssCredential, create_engine, create_schema, create_session_factory
from server_api.services.auth import create_activation_code, open_session
from server_api.services.credentials import save_credentials


def test_sender_decrypts_credentials_only_for_confirmed_order_and_records_success():
    from server_api.workers.sender import process_confirmed_order

    class RecordingSender:
        received: tuple[str, str, str] | None = None

        def __init__(self, appid: str, accid: str, user_sig: str) -> None:
            type(self).received = (appid, accid, user_sig)

        async def send_group_bet(self, group_id: str, play_type: str, amount: float) -> bool:
            assert (group_id, play_type, amount) == ("group-1", "大", 10.0)
            return True

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            code = await create_activation_code(session, activation_code="SEND-CODE", expires_in_seconds=3600)
            user, _ = await open_session(session, machine_code="sender-machine", activation_code="SEND-CODE")
            await save_credentials(
                session, user_id=user.id, appid="10001", accid="accid", user_sig="private-sig", encryption_secret="s" * 32
            )
            order = BetOrder(
                user_id=user.id, site="pc28", period="200", group_id="group-1", play_type="大", amount=10, status="confirmed"
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)

            sent = await process_confirmed_order(
                session, order_id=order.id, encryption_secret="s" * 32, sender_factory=RecordingSender
            )
            assert sent is True
            assert RecordingSender.received == ("10001", "accid", "private-sig")
            assert (await session.get(BetOrder, order.id)).status == "sent"
            attempts = (await session.scalars(select(BetAttempt).where(BetAttempt.order_id == order.id))).all()
            assert [(attempt.status, attempt.error_message) for attempt in attempts] == [("sent", None)]
            events = (await session.scalars(select(StrategyEvent).where(StrategyEvent.user_id == user.id))).all()
            assert [(event.event_type, event.period) for event in events] == [("sent", "200")]
            assert "group-1" in events[0].message and "大10" in events[0].message
        await engine.dispose()

    asyncio.run(scenario())


def test_sender_does_not_decrypt_or_send_pending_order():
    from server_api.workers.sender import process_confirmed_order

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            code = await create_activation_code(session, activation_code="PENDING-CODE", expires_in_seconds=3600)
            user, _ = await open_session(session, machine_code="pending-machine", activation_code="PENDING-CODE")
            order = BetOrder(
                user_id=user.id, site="pc28", period="201", group_id="group-1", play_type="小", amount=10, status="pending_confirmation"
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)

            assert await process_confirmed_order(session, order_id=order.id, encryption_secret="s" * 32, sender_factory=object) is False
            assert (await session.get(BetOrder, order.id)).status == "pending_confirmation"
            assert (await session.scalar(select(BetAttempt).where(BetAttempt.order_id == order.id))) is None
        await engine.dispose()

    asyncio.run(scenario())


def test_sender_refuses_revoked_user_before_decrypting_credentials():
    from server_api.services.auth import revoke_activation_code
    from server_api.workers.sender import process_confirmed_order

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            code = await create_activation_code(session, activation_code="REVOKE-SEND", expires_in_seconds=3600)
            user, _ = await open_session(session, machine_code="revoked-machine", activation_code="REVOKE-SEND")
            await save_credentials(
                session, user_id=user.id, appid="10001", accid="accid", user_sig="private-sig", encryption_secret="s" * 32
            )
            order = BetOrder(
                user_id=user.id, site="pc28", period="202", group_id="group-1", play_type="小", amount=10, status="confirmed"
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            await revoke_activation_code(session, code.id)

            assert await process_confirmed_order(session, order_id=order.id, encryption_secret="s" * 32, sender_factory=object) is False
            assert (await session.get(BetOrder, order.id)).status == "failed"
            attempt = await session.scalar(select(BetAttempt).where(BetAttempt.order_id == order.id))
            assert attempt.error_message == "authorization is inactive"
            event = await session.scalar(select(StrategyEvent).where(StrategyEvent.user_id == user.id))
            assert event.event_type == "failed"
            assert "authorization is inactive" in event.message
        await engine.dispose()

    asyncio.run(scenario())


def test_expire_pending_orders_marks_only_orders_past_confirmation_deadline():
    from server_api.workers.sender import expire_pending_orders

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            code = await create_activation_code(session, activation_code="EXPIRE-CODE", expires_in_seconds=3600)
            user, _ = await open_session(session, machine_code="expire-machine", activation_code="EXPIRE-CODE")
            session.add_all([
                BetOrder(user_id=user.id, site="pc28", period="401", group_id="group", play_type="大", amount=1,
                         status="pending_confirmation", confirmation_deadline_at=datetime.utcnow() - timedelta(seconds=1)),
                BetOrder(user_id=user.id, site="pc28", period="402", group_id="group", play_type="小", amount=1,
                         status="pending_confirmation", confirmation_deadline_at=datetime.utcnow() + timedelta(seconds=60)),
            ])
            await session.commit()
            assert await expire_pending_orders(session) == 1
            statuses = (await session.scalars(select(BetOrder.status).order_by(BetOrder.period))).all()
            assert statuses == ["expired", "pending_confirmation"]
        await engine.dispose()

    asyncio.run(scenario())


def test_sender_refuses_order_after_betting_deadline_before_decrypting_credentials():
    from server_api.workers.sender import process_confirmed_order

    class MustNotConstructSender:
        def __init__(self, *_args: object) -> None:
            raise AssertionError("expired order must not decrypt credentials or construct a sender")

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            code = await create_activation_code(session, activation_code="CLOSE-CODE", expires_in_seconds=3600)
            user, _ = await open_session(session, machine_code="close-machine", activation_code="CLOSE-CODE")
            order = BetOrder(
                user_id=user.id, site="pc28", period="403", group_id="group", play_type="大", amount=1,
                status="confirmed", betting_deadline_at=datetime.utcnow() - timedelta(seconds=1),
            )
            session.add(order)
            await session.commit()

            assert await process_confirmed_order(
                session, order_id=order.id, encryption_secret="s" * 32, sender_factory=MustNotConstructSender
            ) is False
            assert (await session.get(BetOrder, order.id)).status == "expired"
            attempt = await session.scalar(select(BetAttempt).where(BetAttempt.order_id == order.id))
            assert attempt.error_message == "betting window closed"
            event = await session.scalar(select(StrategyEvent).where(StrategyEvent.user_id == user.id))
            assert event.event_type == "expired"
            assert "betting window closed" in event.message
        await engine.dispose()

    asyncio.run(scenario())
