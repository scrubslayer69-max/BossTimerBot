import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import time
import json
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
EGG_CHANNEL_ID_RAW = os.getenv("EGG_CHANNEL_ID")
EGG_CHANNEL_ID = int(EGG_CHANNEL_ID_RAW) if EGG_CHANNEL_ID_RAW else None

DATA_DIR = os.getenv("DATA_DIR", ".")
TIMERS_FILE    = os.path.join(DATA_DIR, "boss_timers.json")
STATE_FILE     = os.path.join(DATA_DIR, "boss_state.json")
EGG_STATE_FILE = os.path.join(DATA_DIR, "egg_state.json")

# ── World boss config ────────────────────────────────────────────────────────

DEFAULT_TIMERS = {
    "hanure":   12 * 3600,
    "morpheus": 8  * 3600,
    "rangora":  8  * 3600,
    "vyrava":   6  * 3600,
    "nazar":    2  * 3600,
    "twt":      48 * 3600,
}
MAINTENANCE_IMMUNE = {"twt"}

# ── Secondary channel config ─────────────────────────────────────────────────

EGG_SIMPLE_TIMERS = {
    "twt":      48 * 3600,
    "morpheus": 8  * 3600,
    "vyrava":   6  * 3600,
}
EGG_SIMPLE_BUTTON_LABELS = {
    "morpheus": "Killed",
    "vyrava":   "Killed",
}

# ── Persistence ───────────────────────────────────────────────────────────────

def load_timers() -> dict:
    if os.path.exists(TIMERS_FILE):
        with open(TIMERS_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_TIMERS.copy()

def save_timers(timers: dict):
    with open(TIMERS_FILE, "w") as f:
        json.dump(timers, f, indent=2)

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def load_egg_state() -> dict:
    if os.path.exists(EGG_STATE_FILE):
        with open(EGG_STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_egg_state(state: dict):
    with open(EGG_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

boss_timers = load_timers()
boss_state  = load_state()
egg_state   = load_egg_state()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

timer_message: discord.Message | None = None
egg_message:   discord.Message | None = None

# ── Utility ───────────────────────────────────────────────────────────────────

def hours_to_seconds(hours: float) -> int:
    return int(hours * 3600)

def seconds_to_hours(seconds: int) -> float:
    return seconds / 3600

def boss_label(boss: str) -> str:
    return boss.upper() if boss == "twt" else boss.capitalize()

# ── World boss message ────────────────────────────────────────────────────────

def build_timer_text() -> str:
    now = time.time()
    lines = ["⚔️ **World Boss Timers**\n"]
    for boss, duration in boss_timers.items():
        lines.append(f"--- **{boss_label(boss)}** ---")
        state = boss_state.get(boss)
        if state and state.get("tod"):
            tod = state["tod"]
            spawn_time = int(tod + duration)
            if state.get("maintenance") or now >= spawn_time:
                lines.append("🟢 **READY!**")
            else:
                lines.append(f"🔴 spawns <t:{spawn_time}:R> (<t:{spawn_time}:t>)")
            lines.append(f"Last known ToD: <t:{int(tod)}:f>")
            killed_by = state.get("killed_by", "Unknown")
            note = state.get("note")
            lines.append(f"Last: **{killed_by}**" + (f" | 💬 {note}" if note else ""))
        else:
            lines.append("🟢 **READY!**")
            lines.append("Last known ToD: N/A")
            lines.append("Last: N/A")
        lines.append("")
    return "\n".join(lines)

def build_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for boss in boss_timers:
        view.add_item(discord.ui.Button(
            label=f"Kill: {boss_label(boss)}",
            custom_id=f"kill_{boss}",
            style=discord.ButtonStyle.primary,
        ))
    view.add_item(discord.ui.Button(label="Maintenance", custom_id="maintenance", style=discord.ButtonStyle.danger))
    view.add_item(discord.ui.Button(label="Undo", custom_id="undo", style=discord.ButtonStyle.secondary))
    return view

async def update_timer_message():
    if timer_message:
        await timer_message.edit(content=build_timer_text(), view=build_view())

# ── Secondary channel message ─────────────────────────────────────────────────

def build_egg_text() -> str:
    now = time.time()
    lines = ["⚔️ **Boss Timers**\n"]
    for boss, duration in EGG_SIMPLE_TIMERS.items():
        lines.append(f"--- **{boss_label(boss)}** ---")
        state = egg_state.get(f"simple_{boss}")
        if state and state.get("kill_time"):
            spawn_time = int(state["kill_time"] + duration)
            if now >= spawn_time:
                lines.append("🟢 **READY!**")
            else:
                lines.append(f"🔴 spawns <t:{spawn_time}:R> (<t:{spawn_time}:t>)")
            lines.append(f"Last known ToD: <t:{int(state['kill_time'])}:f>")
            killed_by = state.get("killed_by", "Unknown")
            note = state.get("note")
            lines.append(f"Last: **{killed_by}**" + (f" | 💬 {note}" if note else ""))
        else:
            lines.append("🟢 **READY!**")
            lines.append("Last known ToD: N/A")
            lines.append("Last: N/A")
        lines.append("")
    return "\n".join(lines)

def build_egg_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for boss in EGG_SIMPLE_TIMERS:
        verb = EGG_SIMPLE_BUTTON_LABELS.get(boss, "Summoned")
        view.add_item(discord.ui.Button(
            label=f"{verb}: {boss_label(boss)}",
            custom_id=f"eggsimple_{boss}",
            style=discord.ButtonStyle.primary,
        ))
    view.add_item(discord.ui.Button(label="Undo", custom_id="egg_undo", style=discord.ButtonStyle.secondary))
    return view

async def update_egg_message():
    if egg_message:
        await egg_message.edit(content=build_egg_text(), view=build_egg_view())

# ── Modals ────────────────────────────────────────────────────────────────────

class NoteModal(discord.ui.Modal, title="Boss Kill Report"):
    note = discord.ui.TextInput(label="Note (optional)", placeholder="e.g. pug raid, didn't see death...", required=False, max_length=100)

    def __init__(self, boss: str):
        super().__init__()
        self.boss = boss

    async def on_submit(self, interaction: discord.Interaction):
        current = boss_state.get(self.boss)
        entry = {"tod": time.time(), "killed_by": interaction.user.display_name, "maintenance": False}
        if current:
            entry["previous"] = {k: v for k, v in current.items() if k != "previous"}
        if self.note.value:
            entry["note"] = self.note.value
        boss_state[self.boss] = entry
        save_state(boss_state)
        await interaction.response.send_message("✅ Updated!", ephemeral=True)
        await update_timer_message()


class SimpleKillModal(discord.ui.Modal, title="Boss Kill Report"):
    note = discord.ui.TextInput(label="Note (optional)", placeholder="e.g. guild run...", required=False, max_length=100)

    def __init__(self, key: str):
        super().__init__()
        self.key = key

    async def on_submit(self, interaction: discord.Interaction):
        current = egg_state.get(self.key)
        entry = {"kill_time": time.time(), "killed_by": interaction.user.display_name}
        if current:
            entry["previous"] = {k: v for k, v in current.items() if k != "previous"}
        if self.note.value:
            entry["note"] = self.note.value
        egg_state[self.key] = entry
        save_egg_state(egg_state)
        await interaction.response.send_message("✅ Updated!", ephemeral=True)
        await update_egg_message()


class MaintenanceConfirm(discord.ui.Modal, title="Confirm Maintenance"):
    confirm = discord.ui.TextInput(label='Type "confirm" to reset all bosses', placeholder="confirm", required=True, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm.value.strip().lower() != "confirm":
            await interaction.response.send_message("❌ Cancelled — type `confirm` to proceed.", ephemeral=True)
            return
        now = time.time()
        for boss in boss_timers:
            if boss in MAINTENANCE_IMMUNE:
                continue
            current = boss_state.get(boss)
            entry = {"tod": now, "killed_by": "Maintenance", "maintenance": True}
            if current:
                entry["previous"] = {k: v for k, v in current.items() if k != "previous"}
            boss_state[boss] = entry
        save_state(boss_state)
        await interaction.response.send_message("✅ Maintenance — all bosses set to READY!", ephemeral=True)
        await update_timer_message()

# ── Undo handlers ─────────────────────────────────────────────────────────────

async def handle_undo(interaction: discord.Interaction):
    options = [discord.SelectOption(label=boss.capitalize(), value=boss) for boss, state in boss_state.items() if state.get("previous")]
    if not options:
        await interaction.response.send_message("❌ Nothing to undo.", ephemeral=True)
        return
    view = discord.ui.View(timeout=60)
    view.add_item(discord.ui.Select(placeholder="Select a boss to undo...", options=options, custom_id="undo_select"))
    await interaction.response.send_message("Select which boss to revert:", view=view, ephemeral=True)

async def handle_undo_select(interaction: discord.Interaction, boss: str):
    state = boss_state.get(boss)
    if not state or not state.get("previous"):
        await interaction.response.send_message("❌ Nothing to undo for that boss.", ephemeral=True)
        return
    boss_state[boss] = state["previous"]
    save_state(boss_state)
    await interaction.response.send_message(f"↩️ Reverted **{boss.capitalize()}** to previous state.", ephemeral=True)
    await update_timer_message()

async def handle_egg_undo(interaction: discord.Interaction):
    def display_label(key: str) -> str:
        return key.removeprefix("simple_").upper() if key.startswith("simple_") else key.title()
    options = [discord.SelectOption(label=display_label(key), value=key) for key, state in egg_state.items() if state.get("previous")]
    if not options:
        await interaction.response.send_message("❌ Nothing to undo.", ephemeral=True)
        return
    view = discord.ui.View(timeout=60)
    view.add_item(discord.ui.Select(placeholder="Select a boss to undo...", options=options, custom_id="egg_undo_select"))
    await interaction.response.send_message("Select which boss to revert:", view=view, ephemeral=True)

async def handle_egg_undo_select(interaction: discord.Interaction, key: str):
    state = egg_state.get(key)
    if not state or not state.get("previous"):
        await interaction.response.send_message("❌ Nothing to undo for that boss.", ephemeral=True)
        return
    egg_state[key] = state["previous"]
    save_egg_state(egg_state)
    await interaction.response.send_message(f"↩️ Reverted to previous state.", ephemeral=True)
    await update_egg_message()

# ── Tasks ─────────────────────────────────────────────────────────────────────

@tasks.loop(seconds=30)
async def refresh_timer():
    try:
        await update_timer_message()
    except Exception as e:
        print(f"Error updating timer message: {e}")
    try:
        await update_egg_message()
    except Exception as e:
        print(f"Error updating egg message: {e}")

@refresh_timer.before_loop
async def before_refresh():
    await bot.wait_until_ready()

# ── Bot events ────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    global timer_message, egg_message
    await bot.tree.sync()

    channel = bot.get_channel(CHANNEL_ID)
    async for msg in channel.history(limit=50):
        if msg.author == bot.user and "World Boss Timers" in msg.content:
            timer_message = msg
            break
    if timer_message:
        await timer_message.edit(content=build_timer_text(), view=build_view())
    else:
        timer_message = await channel.send(content=build_timer_text(), view=build_view())

    if EGG_CHANNEL_ID:
        egg_channel = bot.get_channel(EGG_CHANNEL_ID)
        if egg_channel is None:
            print(f"WARNING: Secondary channel {EGG_CHANNEL_ID} not found — check bot permissions.")
        else:
            async for msg in egg_channel.history(limit=50):
                if msg.author == bot.user and "Boss Timers" in msg.content:
                    egg_message = msg
                    break
            if egg_message:
                await egg_message.edit(content=build_egg_text(), view=build_egg_view())
            else:
                egg_message = await egg_channel.send(content=build_egg_text(), view=build_egg_view())

    refresh_timer.start()
    print(f"Logged in as {bot.user} — slash commands synced.")


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return
    custom_id = interaction.data.get("custom_id", "")

    if custom_id == "maintenance":
        await interaction.response.send_modal(MaintenanceConfirm())
    elif custom_id == "undo":
        await handle_undo(interaction)
    elif custom_id == "undo_select":
        selected = interaction.data.get("values", [])
        if selected:
            await handle_undo_select(interaction, selected[0])
    elif custom_id == "egg_undo":
        await handle_egg_undo(interaction)
    elif custom_id == "egg_undo_select":
        selected = interaction.data.get("values", [])
        if selected:
            await handle_egg_undo_select(interaction, selected[0])
    elif custom_id.startswith("eggsimple_"):
        boss = custom_id.removeprefix("eggsimple_")
        if boss in EGG_SIMPLE_TIMERS:
            await interaction.response.send_modal(SimpleKillModal(f"simple_{boss}"))
    elif custom_id.startswith("kill_"):
        boss = custom_id.removeprefix("kill_")
        if boss in boss_timers:
            await interaction.response.send_modal(NoteModal(boss))

# ── Slash commands ────────────────────────────────────────────────────────────

@bot.tree.command(name="addtimer", description="Add a new world boss with a respawn timer.")
@app_commands.describe(boss="Boss name", hours="Respawn time in hours (decimals OK, e.g. 1.5)")
async def addtimer(interaction: discord.Interaction, boss: str, hours: float):
    key = boss.lower()
    if key in boss_timers:
        await interaction.response.send_message(f"`{key}` already exists. Use `/edittimer` to change it.", ephemeral=True)
        return
    boss_timers[key] = hours_to_seconds(hours)
    save_timers(boss_timers)
    await interaction.response.send_message(f"Added **{key.capitalize()}** with a {hours}h respawn timer.", ephemeral=True)
    await update_timer_message()


@bot.tree.command(name="edittimer", description="Edit the respawn timer for an existing boss.")
@app_commands.describe(boss="Boss name", hours="New respawn time in hours (decimals OK, e.g. 1.5)")
async def edittimer(interaction: discord.Interaction, boss: str, hours: float):
    key = boss.lower()
    updated = []
    if key in boss_timers:
        old = seconds_to_hours(boss_timers[key])
        boss_timers[key] = hours_to_seconds(hours)
        save_timers(boss_timers)
        updated.append(f"World bosses: {old}h → {hours}h")
        await update_timer_message()
    if key in EGG_SIMPLE_TIMERS:
        old = seconds_to_hours(EGG_SIMPLE_TIMERS[key])
        EGG_SIMPLE_TIMERS[key] = hours_to_seconds(hours)
        updated.append(f"Secondary channel: {old}h → {hours}h")
        await update_egg_message()
    if not updated:
        await interaction.response.send_message(f"`{key}` not found.", ephemeral=True)
        return
    await interaction.response.send_message(f"Updated **{key.capitalize()}**:\n" + "\n".join(updated), ephemeral=True)


@bot.tree.command(name="removetimer", description="Remove a world boss from the timer list.")
@app_commands.describe(boss="Boss name to remove")
async def removetimer(interaction: discord.Interaction, boss: str):
    key = boss.lower()
    if key not in boss_timers:
        await interaction.response.send_message(f"`{key}` not found.", ephemeral=True)
        return
    del boss_timers[key]
    save_timers(boss_timers)
    boss_state.pop(key, None)
    save_state(boss_state)
    await interaction.response.send_message(f"Removed **{key.capitalize()}** from the timer list.", ephemeral=True)
    await update_timer_message()


@bot.tree.command(name="listtimers", description="List all world bosses and their respawn timers.")
async def listtimers(interaction: discord.Interaction):
    if not boss_timers:
        await interaction.response.send_message("No bosses configured.", ephemeral=True)
        return
    lines = [f"**{boss_label(k)}** — {seconds_to_hours(v)}h" for k, v in boss_timers.items()]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="settimer", description="Manually set how long is left on a secondary channel boss timer.")
@app_commands.describe(boss="Which boss", days="Days remaining", hours="Hours remaining", minutes="Minutes remaining", seconds="Seconds remaining")
@app_commands.choices(boss=[
    app_commands.Choice(name="TWT",      value="twt"),
    app_commands.Choice(name="Morpheus", value="morpheus"),
    app_commands.Choice(name="Vyrava",   value="vyrava"),
])
async def settimer(interaction: discord.Interaction, boss: str, days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0):
    total_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds
    if total_seconds <= 0:
        await interaction.response.send_message("❌ Please provide a time greater than zero.", ephemeral=True)
        return
    duration = EGG_SIMPLE_TIMERS[boss]
    if total_seconds > duration:
        await interaction.response.send_message(f"❌ Time remaining cannot exceed {seconds_to_hours(duration)}h for {boss_label(boss)}.", ephemeral=True)
        return
    key = f"simple_{boss}"
    kill_time = time.time() - (duration - total_seconds)
    current = egg_state.get(key)
    entry = {"kill_time": kill_time, "killed_by": current.get("killed_by", "Unknown") if current else "Unknown"}
    if current:
        entry["previous"] = {k: v for k, v in current.items() if k != "previous"}
    egg_state[key] = entry
    save_egg_state(egg_state)
    parts = []
    if days:    parts.append(f"{days}d")
    if hours:   parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    if seconds: parts.append(f"{seconds}s")
    await interaction.response.send_message(f"✅ **{boss_label(boss)}** timer set — spawns in **{' '.join(parts)}**.", ephemeral=True)
    await update_egg_message()


bot.run(TOKEN)
