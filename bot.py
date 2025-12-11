import os
import discord
from discord.ext import commands
from datetime import datetime, timezone

# ====== 環境変数から設定を読む ======
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID_STR = os.getenv("GUILD_ID")  # 例: "123456789012345678"

if GUILD_ID_STR is None:
    raise RuntimeError("環境変数 GUILD_ID が設定されていません。Render の Environment に追加してください。")

GUILD_ID = int(GUILD_ID_STR)
LOG_CATEGORY_NAME = "VCログ"
# ================================

intents = discord.Intents.default()
intents.members = True          # メンバー情報取得
intents.voice_states = True     # VCの入退室イベント
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# (guild_id, member_id) -> join_time(UTC)
voice_join_times: dict[tuple[int, int], datetime] = {}


def format_timedelta(delta):
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        total_seconds = 0

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    parts = []
    if hours:
        parts.append(f"{hours}時間")
    if minutes:
        parts.append(f"{minutes}分")
    if seconds or not parts:
        parts.append(f"{seconds}秒")

    return "".join(parts)


async def get_or_create_log_channel(member: discord.Member) -> discord.TextChannel:
    guild = member.guild
    print(f"[DEBUG] get_or_create_log_channel for member {member} in guild {guild.id}")

    # カテゴリを探す or 作る
    category = discord.utils.get(guild.categories, name=LOG_CATEGORY_NAME)
    if category is None:
        print("[DEBUG] VCログカテゴリがないので作成します")
        category = await guild.create_category(LOG_CATEGORY_NAME)

    channel_name = f"vc-log-{member.id}"

    # 既にあるかチェック
    channel = discord.utils.get(category.text_channels, name=channel_name)
    if channel is None:
        print(f"[DEBUG] ログ用テキストチャンネル {channel_name} がないので作成します")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True, send_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"{member.display_name} のVCログ",
        )
    else:
        print(f"[DEBUG] 既存のログチャンネル {channel_name} を使用します")

    return channel


@bot.event
async def on_ready():
    print("===================================")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"監視対象の GUILD_ID: {GUILD_ID}")
    print("Bot がオンラインになりました")
    print("===================================")


@bot.event
async def on_voice_state_update(member: discord.Member,
                                before: discord.VoiceState,
                                after: discord.VoiceState):

    # デバッグ用ログ
    print("----- on_voice_state_update -----")
    print(f"member: {member} (id={member.id})")
    print(f"guild.id: {member.guild.id}, target GUILD_ID: {GUILD_ID}")

    # 対象サーバー以外は無視
    if member.guild.id != GUILD_ID:
        print("[DEBUG] 別のギルドのイベントなので無視します")
        return

    if member.bot:
        print("[DEBUG] Botユーザーなので無視します")
        return

    print(f"[DEBUG] before.channel = {getattr(before.channel, 'name', None)}")
    print(f"[DEBUG] after.channel  = {getattr(after.channel, 'name', None)}")

    joined_channel = None
    left_channel = None

    if before.channel is None and after.channel is not None:
        joined_channel = after.channel
        print(f"[DEBUG] join: {joined_channel.name}")
    elif before.channel is not None and after.channel is None:
        left_channel = before.channel
        print(f"[DEBUG] leave: {left_channel.name}")
    elif (
        before.channel is not None
        and after.channel is not None
        and before.channel.id != after.channel.id
    ):
        left_channel = before.channel
        joined_channel = after.channel
        print(f"[DEBUG] move: {left_channel.name} -> {joined_channel.name}")
    else:
        print("[DEBUG] 実質的なチャンネル変化なし（ミュートなど）")
        return

    log_channel = await get_or_create_log_channel(member)

    now = datetime.now(timezone.utc)
    key = (member.guild.id, member.id)

    if left_channel is not None:
        if key in voice_join_times:
            joined_at = voice_join_times.pop(key)
            stay_time = now - joined_at
            stay_str = format_timedelta(stay_time)
            leave_message = (
                f"❌ {member.mention} が **{left_channel.name}** から退出しました。\n"
                f"　滞在時間: {stay_str}"
            )
        else:
            leave_message = (
                f"❌ {member.mention} が **{left_channel.name}** から退出しました。\n"
                f"　滞在時間: 不明（入室時刻の記録なし）"
            )
        print(f"[DEBUG] 退出ログを送信: {leave_message}")
        await log_channel.send(leave_message)

    if joined_channel is not None:
        voice_join_times[key] = now
        join_message = (
            f"✅ {member.mention} が **{joined_channel.name}** に参加しました。"
        )
        print(f"[DEBUG] 入室ログを送信: {join_message}")
        await log_channel.send(join_message)


bot.run(TOKEN)
