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
TIMERS_FILE = "boss_timers.json"
STATE_FILE = "boss_state.json"

DEFAULT_TIMERS = {
    "hanure":   12 * 3600,
    "morpheus": 8  * 3600,
    "rangora":  8  * 3600,
    "vyrava":   6  * 3600,
    "nazar":    2  * 3600,
}


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


boss_timers = load_timers()
boss_state = load_state()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

timer_message: discord.Message | None = None


def hours_to_seconds(hours: float) -> int:
    return int(hours * 3600)


def seconds_to_hours(seconds: int) -> float:
    return seconds / 3600


def build_timer_text() -> str:
    now = time.time()
    lines = ["⚔️ **World Boss Timers**\n"]
    for boss, duration in boss_timers.items():
        name = boss.capitalize()
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
        button = discord.ui.Button(
            label=f"Kill: {boss.capitalize()}",
            custom_id=f"kill_{boss}",
            style=discord.ButtonStyle.primary,
        )
        view.add_item(button)
    maint_button = discord.ui.Button(
        label="Maintenance",
        custom_id="maintenance",
        style=discord.ButtonStyle.danger,
    )
    view.add_item(maint_button)
    return view


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
        entry = {
            "tod": time.time(),
            "killed_by": interaction.user.display_name,
            "maintenance": False,
        }
        if self.note.value:
            entry["note"] = self.note.value
        boss_state[self.boss] = entry
        save_state(boss_state)
        await interaction.response.send_message("✅ Updated!", ephemeral=True)
        await update_timer_message()


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
            boss_state[boss] = {
                "tod": now,
                "killed_by": "Maintenance",
                "maintenance": True,
            }
        save_state(boss_state)
        await interaction.response.send_message("✅ Maintenance — all bosses set to READY!", ephemeral=True)
        await update_timer_message()


async def handle_kill(interaction: discord.Interaction, boss: str):
    await interaction.response.send_modal(NoteModal(boss))


async def update_timer_message():
    if timer_message:
        await timer_message.edit(content=build_timer_text(), view=build_view())


@tasks.loop(minutes=1)
async def refresh_timer():
    await update_timer_message()


@bot.event
async def on_ready():
    global timer_message
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

    refresh_timer.start()
    print(f"Logged in as {bot.user} — slash commands synced.")


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return
    custom_id = interaction.data.get("custom_id", "")
    if custom_id == "maintenance":
        await interaction.response.send_modal(MaintenanceConfirm())
    elif custom_id.startswith("kill_"):
        boss = custom_id.removeprefix("kill_")
        if boss in boss_timers:
            await handle_kill(interaction, boss)


@bot.tree.command(name="addtimer", description="Add a new boss with a respawn timer.")
@app_commands.describe(boss="Boss name", hours="Respawn time in hours (decimals OK, e.g. 1.5)")
async def addtimer(interaction: discord.Interaction, boss: str, hours: float):
    key = boss.lower()
    if key in boss_timers:
        await interaction.response.send_message(
            f"`{key}` already exists. Use `/edittimer` to change it.", ephemeral=True
        )
        return
    boss_timers[key] = hours_to_seconds(hours)
    save_timers(boss_timers)
    await interaction.response.send_message(
        f"Added **{key.capitalize()}** with a {hours}h respawn timer.", ephemeral=True
    )
    await update_timer_message()


@bot.tree.command(name="edittimer", description="Edit the respawn timer for an existing boss.")
@app_commands.describe(boss="Boss name", hours="New respawn time in hours (decimals OK, e.g. 1.5)")
async def edittimer(interaction: discord.Interaction, boss: str, hours: float):
    key = boss.lower()
    if key not in boss_timers:
        await interaction.response.send_message(
            f"`{key}` not found. Use `/addtimer` to add it.", ephemeral=True
        )
        return
    old = seconds_to_hours(boss_timers[key])
    boss_timers[key] = hours_to_seconds(hours)
    save_timers(boss_timers)
    await interaction.response.send_message(
        f"Updated **{key.capitalize()}**: {old}h → {hours}h", ephemeral=True
    )
    await update_timer_message()


@bot.tree.command(name="removetimer", description="Remove a boss from the timer list.")
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
    await interaction.response.send_message(
        f"Removed **{key.capitalize()}** from the timer list.", ephemeral=True
    )
    await update_timer_message()


@bot.tree.command(name="listtimers", description="List all bosses and their respawn timers.")
async def listtimers(interaction: discord.Interaction):
    if not boss_timers:
        await interaction.response.send_message("No bosses configured.", ephemeral=True)
        return
    lines = [f"**{k.capitalize()}** — {seconds_to_hours(v)}h" for k, v in boss_timers.items()]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


bot.run(TOKEN)
