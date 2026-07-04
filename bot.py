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
TIMERS_FILE = os.path.join(DATA_DIR, "boss_timers.json")
STATE_FILE = os.path.join(DATA_DIR, "boss_state.json")
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

# ── Egg boss config ──────────────────────────────────────────────────────────

EGG_COOLDOWN_SECS = 2 * 3600
EGG_WINDOW_SECS   = 1 * 3600

EGG_BOSS_CONFIG = {
    "red dragon": {"icon": "🔴", "grow": 51  * 3600},
    "kraken":     {"icon": "🔵", "grow": 51  * 3600},
    "berserker":  {"icon": "🟢", "grow": (5 * 24 + 22) * 3600},  # 142h
}
EGG_BOSSES = list(EGG_BOSS_CONFIG.keys())
EGG_SIMPLE_TIMERS = {"twt": 48 * 3600}

# ── Persistence helpers ──────────────────────────────────────────────────────

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
boss_state = load_state()
egg_state = load_egg_state()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

timer_message: discord.Message | None = None
egg_message: discord.Message | None = None

# ── Utility ──────────────────────────────────────────────────────────────────

def hours_to_seconds(hours: float) -> int:
    return int(hours * 3600)

def seconds_to_hours(seconds: int) -> float:
    return seconds / 3600

def get_egg_status(summon_time: float, grow_secs: int) -> tuple[str, int, int, int]:
    """Returns (status, cooldown_end, grow_end, window_end) for a given summon time."""
    now = time.time()
    cycle_secs = EGG_COOLDOWN_SECS + grow_secs + EGG_WINDOW_SECS
    elapsed = now - summon_time
    cycle_num = int(elapsed // cycle_secs)
    cycle_start = summon_time + cycle_num * cycle_secs
    cooldown_end = int(cycle_start + EGG_COOLDOWN_SECS)
    grow_end     = int(cycle_start + EGG_COOLDOWN_SECS + grow_secs)
    window_end   = int(cycle_start + cycle_secs)
    pos = now - cycle_start
    if pos < EGG_COOLDOWN_SECS:
        status = "cooldown"
    elif pos < EGG_COOLDOWN_SECS + grow_secs:
        status = "growing"
    else:
        status = "ready"
    return status, cooldown_end, grow_end, window_end

# ── World boss message ───────────────────────────────────────────────────────

def build_timer_text() -> str:
    now = time.time()
    lines = ["⚔️ **World Boss Timers**\n"]
    for boss, duration in boss_timers.items():
        name = boss.upper() if boss == "twt" else boss.capitalize()
        lines.append(f"--- **{name}** ---")
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
            if note:
                lines.append(f"Last: **{killed_by}** | 💬 {note}")
            else:
                lines.append(f"Last: **{killed_by}**")
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
            label=f"Kill: {boss.upper() if boss == 'twt' else boss.capitalize()}",
            custom_id=f"kill_{boss}",
            style=discord.ButtonStyle.primary,
        ))
    view.add_item(discord.ui.Button(
        label="Maintenance",
        custom_id="maintenance",
        style=discord.ButtonStyle.danger,
    ))
    view.add_item(discord.ui.Button(
        label="Undo",
        custom_id="undo",
        style=discord.ButtonStyle.secondary,
    ))
    return view

async def update_timer_message():
    if timer_message:
        await timer_message.edit(content=build_timer_text(), view=build_view())

# ── Egg boss message ─────────────────────────────────────────────────────────

def build_egg_text() -> str:
    lines = ["🥚 **Egg Boss Timers**\n"]
    for boss, cfg in EGG_BOSS_CONFIG.items():
        icon = cfg["icon"]
        grow_secs = cfg["grow"]
        lines.append(f"--- {icon} **{boss.title()}** ---")
        state = egg_state.get(boss)
        if state and state.get("summon_time"):
            status, cooldown_end, grow_end, window_end = get_egg_status(state["summon_time"], grow_secs)
            if status == "cooldown":
                lines.append(f"⏳ **Cooldown** — grows <t:{cooldown_end}:R> (<t:{cooldown_end}:t>)")
            elif status == "growing":
                lines.append(f"🥚 Growing — ready <t:{grow_end}:R> (<t:{grow_end}:t>)")
            else:
                lines.append(f"🟢 **READY** — window closes <t:{window_end}:R> (<t:{window_end}:t>)")
            lines.append(f"Last pop: <t:{int(state['summon_time'])}:f>")
            popped_by = state.get("popped_by", "Unknown")
            note = state.get("note")
            if note:
                lines.append(f"Last: **{popped_by}** | 💬 {note}")
            else:
                lines.append(f"Last: **{popped_by}**")
        else:
            lines.append("🟢 **READY** — no pop recorded yet")
            lines.append("Last pop: N/A")
            lines.append("Last: N/A")
        lines.append("")
    now = time.time()
    for boss, duration in EGG_SIMPLE_TIMERS.items():
        lines.append(f"--- **{boss.upper()}** ---")
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
            if note:
                lines.append(f"Last: **{killed_by}** | 💬 {note}")
            else:
                lines.append(f"Last: **{killed_by}**")
        else:
            lines.append("🟢 **READY!**")
            lines.append("Last known ToD: N/A")
            lines.append("Last: N/A")
        lines.append("")
    return "\n".join(lines)

def build_egg_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for boss in EGG_BOSSES:
        view.add_item(discord.ui.Button(
            label=f"Summoned: {boss.title()}",
            custom_id=f"eggkill_{boss}",
            style=discord.ButtonStyle.primary,
        ))
    for boss in EGG_SIMPLE_TIMERS:
        view.add_item(discord.ui.Button(
            label=f"Summoned: {boss.upper()}",
            custom_id=f"eggsimple_{boss}",
            style=discord.ButtonStyle.primary,
        ))
    view.add_item(discord.ui.Button(
        label="Undo",
        custom_id="egg_undo",
        style=discord.ButtonStyle.secondary,
    ))
    return view

async def update_egg_message():
    if egg_message:
        await egg_message.edit(content=build_egg_text(), view=build_egg_view())

# ── Modals ───────────────────────────────────────────────────────────────────

class NoteModal(discord.ui.Modal, title="Boss Kill Report"):
    note = discord.ui.TextInput(
        label="Note (optional)",
        placeholder="e.g. pug raid, didn't see death...",
        required=False,
        max_length=100,
    )

    def __init__(self, boss: str):
        super().__init__()
        self.boss = boss

    async def on_submit(self, interaction: discord.Interaction):
        current = boss_state.get(self.boss)
        entry = {
            "tod": time.time(),
            "killed_by": interaction.user.display_name,
            "maintenance": False,
        }
        if current:
            entry["previous"] = {k: v for k, v in current.items() if k != "previous"}
        if self.note.value:
            entry["note"] = self.note.value
        boss_state[self.boss] = entry
        save_state(boss_state)
        await interaction.response.send_message("✅ Updated!", ephemeral=True)
        await update_timer_message()


class EggKillModal(discord.ui.Modal, title="Egg Pop Report"):
    note = discord.ui.TextInput(
        label="Note (optional)",
        placeholder="e.g. solo, guild run...",
        required=False,
        max_length=100,
    )

    def __init__(self, boss: str):
        super().__init__()
        self.boss = boss

    async def on_submit(self, interaction: discord.Interaction):
        current = egg_state.get(self.boss)
        entry = {
            "summon_time": time.time(),
            "popped_by": interaction.user.display_name,
        }
        if current:
            entry["previous"] = {k: v for k, v in current.items() if k != "previous"}
        if self.note.value:
            entry["note"] = self.note.value
        egg_state[self.boss] = entry
        save_egg_state(egg_state)
        await interaction.response.send_message("✅ Pop recorded — 2h cooldown started!", ephemeral=True)
        await update_egg_message()


class MaintenanceConfirm(discord.ui.Modal, title="Confirm Maintenance"):
    confirm = discord.ui.TextInput(
        label='Type "confirm" to reset all bosses',
        placeholder="confirm",
        required=True,
        max_length=10,
    )

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
    options = [
        discord.SelectOption(label=boss.capitalize(), value=boss)
        for boss, state in boss_state.items() if state.get("previous")
    ]
    if not options:
        await interaction.response.send_message("❌ Nothing to undo.", ephemeral=True)
        return
    view = discord.ui.View(timeout=60)
    view.add_item(discord.ui.Select(
        placeholder="Select a boss to undo...",
        options=options,
        custom_id="undo_select",
    ))
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
        if key.startswith("simple_"):
            return key.removeprefix("simple_").upper()
        return key.title()

    options = [
        discord.SelectOption(label=display_label(boss), value=boss)
        for boss, state in egg_state.items() if state.get("previous")
    ]
    if not options:
        await interaction.response.send_message("❌ Nothing to undo.", ephemeral=True)
        return
    view = discord.ui.View(timeout=60)
    view.add_item(discord.ui.Select(
        placeholder="Select a boss to undo...",
        options=options,
        custom_id="egg_undo_select",
    ))
    await interaction.response.send_message("Select which egg boss to revert:", view=view, ephemeral=True)

async def handle_egg_undo_select(interaction: discord.Interaction, boss: str):
    state = egg_state.get(boss)
    if not state or not state.get("previous"):
        await interaction.response.send_message("❌ Nothing to undo for that boss.", ephemeral=True)
        return
    egg_state[boss] = state["previous"]
    save_egg_state(egg_state)
    await interaction.response.send_message(f"↩️ Reverted **{boss.title()}** to previous state.", ephemeral=True)
    await update_egg_message()

# ── Tasks ─────────────────────────────────────────────────────────────────────

@tasks.loop(minutes=1)
async def refresh_timer():
    await update_timer_message()
    await update_egg_message()

# ── Bot events ────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    global timer_message, egg_message
    await bot.tree.sync()

    # World boss channel
    channel = bot.get_channel(CHANNEL_ID)
    async for msg in channel.history(limit=50):
        if msg.author == bot.user and "World Boss Timers" in msg.content:
            timer_message = msg
            break
    if timer_message:
        await timer_message.edit(content=build_timer_text(), view=build_view())
    else:
        timer_message = await channel.send(content=build_timer_text(), view=build_view())

    # Egg boss channel
    if EGG_CHANNEL_ID:
        egg_channel = bot.get_channel(EGG_CHANNEL_ID)
        if egg_channel is None:
            print(f"WARNING: Egg channel {EGG_CHANNEL_ID} not found — check bot has access to the channel.")
        else:
            async for msg in egg_channel.history(limit=50):
                if msg.author == bot.user and "Egg Boss Timers" in msg.content:
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
            await interaction.response.send_modal(EggKillModal(f"simple_{boss}"))
    elif custom_id.startswith("eggkill_"):
        boss = custom_id.removeprefix("eggkill_")
        if boss in EGG_BOSSES:
            await interaction.response.send_modal(EggKillModal(boss))
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


@bot.tree.command(name="edittimer", description="Edit the respawn timer for an existing world boss.")
@app_commands.describe(boss="Boss name", hours="New respawn time in hours (decimals OK, e.g. 1.5)")
async def edittimer(interaction: discord.Interaction, boss: str, hours: float):
    key = boss.lower()
    if key not in boss_timers:
        await interaction.response.send_message(f"`{key}` not found. Use `/addtimer` to add it.", ephemeral=True)
        return
    old = seconds_to_hours(boss_timers[key])
    boss_timers[key] = hours_to_seconds(hours)
    save_timers(boss_timers)
    await interaction.response.send_message(f"Updated **{key.capitalize()}**: {old}h → {hours}h", ephemeral=True)
    await update_timer_message()


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
    lines = [f"**{k.capitalize()}** — {seconds_to_hours(v)}h" for k, v in boss_timers.items()]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="settimer", description="Manually set how long is left on an egg's grow timer.")
@app_commands.describe(
    boss="Which egg boss",
    hours="Hours remaining (0–53)",
    minutes="Minutes remaining (0–59)",
    seconds="Seconds remaining (0–59)",
)
@app_commands.choices(boss=[
    app_commands.Choice(name="Red Dragon", value="red dragon"),
    app_commands.Choice(name="Kraken",     value="kraken"),
    app_commands.Choice(name="Berserker",  value="berserker"),
])
async def settimer(
    interaction: discord.Interaction,
    boss: str,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
):
    total_seconds = hours * 3600 + minutes * 60 + seconds
    grow_secs = EGG_BOSS_CONFIG[boss]["grow"]
    if total_seconds <= 0:
        await interaction.response.send_message("❌ Please provide a time greater than zero.", ephemeral=True)
        return
    if total_seconds > grow_secs:
        max_h = grow_secs // 3600
        await interaction.response.send_message(f"❌ Time remaining cannot exceed {max_h} hours for {boss.title()}.", ephemeral=True)
        return

    # Back-calculate so the egg appears mid-grow with the correct time remaining
    summon_time = time.time() - (EGG_COOLDOWN_SECS + grow_secs - total_seconds)
    current = egg_state.get(boss)
    entry = {
        "summon_time": summon_time,
        "popped_by": interaction.user.display_name,
    }
    if current:
        entry["previous"] = {k: v for k, v in current.items() if k != "previous"}
    egg_state[boss] = entry
    save_egg_state(egg_state)

    parts = []
    if hours:   parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    if seconds: parts.append(f"{seconds}s")
    await interaction.response.send_message(
        f"✅ **{boss.title()}** egg timer set — ready in **{' '.join(parts)}**.", ephemeral=True
    )
    await update_egg_message()


bot.run(TOKEN)
