import os
import time

import aiosqlite

from utils.leveling import level_from_xp


class Database:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS mod_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS xp (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    xp INTEGER NOT NULL DEFAULT 0,
                    last_message_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS membership (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    tier TEXT NOT NULL,
                    granted_by INTEGER,
                    granted_at REAL NOT NULL,
                    expires_at REAL,
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at REAL NOT NULL,
                    closed_at REAL,
                    closed_by INTEGER
                );

                CREATE TABLE IF NOT EXISTS giveaways (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    prize TEXT NOT NULL,
                    winners_count INTEGER NOT NULL DEFAULT 1,
                    end_time REAL NOT NULL,
                    host_id INTEGER,
                    ended INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS giveaway_entries (
                    giveaway_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (giveaway_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS faq (
                    guild_id INTEGER NOT NULL,
                    trigger TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    PRIMARY KEY (guild_id, trigger)
                );

                CREATE TABLE IF NOT EXISTS stickies (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    last_message_id INTEGER,
                    set_by INTEGER,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (guild_id, channel_id)
                );

                CREATE TABLE IF NOT EXISTS daily_claims (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    last_claim_at REAL NOT NULL DEFAULT 0,
                    streak INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                );
                """
            )
            await db.commit()

    # ---------- Moderation ----------

    async def add_mod_action(self, guild_id, user_id, moderator_id, action, reason):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO mod_actions (guild_id, user_id, moderator_id, action, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, user_id, moderator_id, action, reason, time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())),
            )
            await db.commit()

    async def get_warnings(self, guild_id, user_id):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM mod_actions WHERE guild_id = ? AND user_id = ? AND action = 'warn' ORDER BY id DESC",
                (guild_id, user_id),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def count_warnings(self, guild_id, user_id):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM mod_actions WHERE guild_id = ? AND user_id = ? AND action = 'warn'",
                (guild_id, user_id),
            )
            (count,) = await cursor.fetchone()
            return count

    async def clear_warnings(self, guild_id, user_id):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM mod_actions WHERE guild_id = ? AND user_id = ? AND action = 'warn'",
                (guild_id, user_id),
            )
            await db.commit()
            return cursor.rowcount

    # ---------- XP ----------

    async def try_add_xp(self, guild_id, user_id, amount, cooldown_seconds):
        """Returns None if the user is still on cooldown, else (new_xp, old_level, new_level)."""
        now = time.time()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT xp, last_message_at FROM xp WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            )
            row = await cursor.fetchone()
            if row and (now - row["last_message_at"]) < cooldown_seconds:
                return None

            old_xp = row["xp"] if row else 0
            old_level = level_from_xp(old_xp)
            new_xp = old_xp + amount
            new_level = level_from_xp(new_xp)

            await db.execute(
                """
                INSERT INTO xp (guild_id, user_id, xp, last_message_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = excluded.xp, last_message_at = excluded.last_message_at
                """,
                (guild_id, user_id, new_xp, now),
            )
            await db.commit()
            return new_xp, old_level, new_level

    async def get_xp(self, guild_id, user_id):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT xp FROM xp WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = await cursor.fetchone()
            xp = row[0] if row else 0
            return xp, level_from_xp(xp)

    async def get_leaderboard(self, guild_id, limit=10):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT user_id, xp FROM xp WHERE guild_id = ? ORDER BY xp DESC LIMIT ?", (guild_id, limit)
            )
            rows = await cursor.fetchall()
            return [(user_id, xp, level_from_xp(xp)) for user_id, xp in rows]

    # ---------- Membership ----------

    async def grant_membership(self, guild_id, user_id, tier, granted_by, expires_at):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO membership (guild_id, user_id, tier, granted_by, granted_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    tier = excluded.tier, granted_by = excluded.granted_by,
                    granted_at = excluded.granted_at, expires_at = excluded.expires_at
                """,
                (guild_id, user_id, tier, granted_by, time.time(), expires_at),
            )
            await db.commit()

    async def revoke_membership(self, guild_id, user_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM membership WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            await db.commit()

    async def get_membership(self, guild_id, user_id):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM membership WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def extend_membership(self, guild_id, user_id, extra_seconds):
        record = await self.get_membership(guild_id, user_id)
        if not record:
            return None
        base = record["expires_at"] if record["expires_at"] else time.time()
        new_expiry = base + extra_seconds
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE membership SET expires_at = ? WHERE guild_id = ? AND user_id = ?",
                (new_expiry, guild_id, user_id),
            )
            await db.commit()
        record["expires_at"] = new_expiry
        return record

    async def get_expired_memberships(self, guild_id, now_ts):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM membership WHERE guild_id = ? AND expires_at IS NOT NULL AND expires_at <= ?",
                (guild_id, now_ts),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ---------- Tickets ----------

    async def create_ticket(self, guild_id, channel_id, user_id):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "INSERT INTO tickets (guild_id, channel_id, user_id, status, created_at) VALUES (?, ?, ?, 'open', ?)",
                (guild_id, channel_id, user_id, time.time()),
            )
            await db.commit()
            return cursor.lastrowid

    async def get_open_ticket(self, guild_id, user_id):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'", (guild_id, user_id)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_ticket_by_channel(self, channel_id):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def close_ticket(self, ticket_id, closed_by):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE tickets SET status = 'closed', closed_at = ?, closed_by = ? WHERE id = ?",
                (time.time(), closed_by, ticket_id),
            )
            await db.commit()

    # ---------- Giveaways ----------

    async def create_giveaway(self, guild_id, channel_id, message_id, prize, winners_count, end_time, host_id):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "INSERT INTO giveaways (guild_id, channel_id, message_id, prize, winners_count, end_time, host_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (guild_id, channel_id, message_id, prize, winners_count, end_time, host_id),
            )
            await db.commit()
            return cursor.lastrowid

    async def add_giveaway_entry(self, giveaway_id, user_id):
        async with aiosqlite.connect(self.path) as db:
            try:
                await db.execute(
                    "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)", (giveaway_id, user_id)
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def get_giveaway_entries(self, giveaway_id):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,))
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

    async def get_active_giveaways(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM giveaways WHERE ended = 0")
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_giveaway_by_message(self, message_id):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM giveaways WHERE message_id = ?", (message_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def end_giveaway(self, giveaway_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE giveaways SET ended = 1 WHERE id = ?", (giveaway_id,))
            await db.commit()

    # ---------- FAQ ----------

    async def get_faq(self, guild_id):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT trigger, answer FROM faq WHERE guild_id = ?", (guild_id,))
            rows = await cursor.fetchall()
            return {trigger: answer for trigger, answer in rows}

    async def set_faq(self, guild_id, trigger, answer):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO faq (guild_id, trigger, answer) VALUES (?, ?, ?)
                ON CONFLICT(guild_id, trigger) DO UPDATE SET answer = excluded.answer
                """,
                (guild_id, trigger, answer),
            )
            await db.commit()

    async def delete_faq(self, guild_id, trigger):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("DELETE FROM faq WHERE guild_id = ? AND trigger = ?", (guild_id, trigger))
            await db.commit()
            return cursor.rowcount > 0

    async def seed_faq_if_empty(self, guild_id, faq_dict):
        for trigger, answer in faq_dict.items():
            await self.set_faq(guild_id, trigger.lower(), answer)

    # ---------- Stickies ----------

    async def set_sticky(self, guild_id, channel_id, content, set_by, message_id=None):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO stickies (guild_id, channel_id, content, last_message_id, set_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                    content = excluded.content, last_message_id = excluded.last_message_id,
                    set_by = excluded.set_by, updated_at = excluded.updated_at
                """,
                (guild_id, channel_id, content, message_id, set_by, time.time()),
            )
            await db.commit()

    async def get_sticky(self, guild_id, channel_id):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM stickies WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_sticky_message(self, guild_id, channel_id, message_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE stickies SET last_message_id = ? WHERE guild_id = ? AND channel_id = ?",
                (message_id, guild_id, channel_id),
            )
            await db.commit()

    async def remove_sticky(self, guild_id, channel_id):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM stickies WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    # ---------- Daily rewards ----------

    async def claim_daily(self, guild_id, user_id, base_xp, streak_bonus_xp, now=None):
        """Attempts to claim the daily XP reward.

        Returns (awarded, streak, seconds_until_next):
          - Still on cooldown: (None, current_streak, seconds_remaining)
          - Claimed successfully: (xp_awarded, new_streak, 0)

        A streak continues if the previous claim was within the last 48 hours (missing part of a
        day is forgiven, but two full days off resets it back to 1).
        """
        now = now if now is not None else time.time()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                "SELECT last_claim_at, streak FROM daily_claims WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()

            if row:
                elapsed = now - row["last_claim_at"]
                if elapsed < 86400:
                    return None, row["streak"], int(86400 - elapsed)
                streak = row["streak"] + 1 if elapsed < 172800 else 1
            else:
                streak = 1

            awarded = base_xp + streak_bonus_xp * (streak - 1)

            await db.execute(
                """
                INSERT INTO daily_claims (guild_id, user_id, last_claim_at, streak) VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    last_claim_at = excluded.last_claim_at, streak = excluded.streak
                """,
                (guild_id, user_id, now, streak),
            )

            xp_cursor = await db.execute("SELECT xp FROM xp WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            xp_row = await xp_cursor.fetchone()
            new_xp = (xp_row["xp"] if xp_row else 0) + awarded
            await db.execute(
                """
                INSERT INTO xp (guild_id, user_id, xp, last_message_at) VALUES (?, ?, ?, 0)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = excluded.xp
                """,
                (guild_id, user_id, new_xp),
            )
            await db.commit()

        return awarded, streak, 0
