import discord
from discord.ext import commands
from datetime import datetime, timezone

# ====== 設定ここを自分の環境に合わせて変える ======
import os
TOKEN = os.getenv("DISCORD_TOKEN")  # ←環境変数から取る
GUILD_ID = 123456789012345678      # ログを取りたいサーバーID
LOG_CATEGORY_NAME = "VCログ"       # ユーザーのVCログチャンネルをまとめるカテゴリ名
# ===================================================

intents = discord.Intents.default()
intents.message_content = False  # このBotでは不要
intents.members = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# (guild_id, member_id) -> join_time(UTC)
voice_join_times: dict[tuple[int, int], datetime] = {}


def format_timedelta(delta):
    """timedelta を 'X時間Y分Z秒' みたいな日本語に整形"""
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
    """
    メンバーに対応するログ用テキストチャンネルを取得 or 作成
    「VCログ」カテゴリ配下に vc-log-<user_id> というチャンネルを作る
    """
    guild = member.guild

    # カテゴリを探す or 作る
    category = discord.utils.get(guild.categories, name=LOG_CATEGORY_NAME)
    if category is None:
        category = await guild.create_category(LOG_CATEGORY_NAME)

    # チャンネル名は user id で一意に
    channel_name = f"vc-log-{member.id}"

    # 既にあるかチェック
    channel = discord.utils.get(category.text_channels, name=channel_name)
    if channel is None:
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

    return channel


@bot.event
async def on_voice_state_update(member: discord.Member,
                                before: discord.VoiceState,
                                after: discord.VoiceState):

    # Bot自身は無視
    if member.bot:
        return

    # ログを取りたいサーバーだけ対象
    if member.guild.id != GUILD_ID:
        return

    joined_channel = None
    left_channel = None

    # 状態の変化を判定
    if before.channel is None and after.channel is not None:
        # VCに入った
        joined_channel = after.channel
    elif before.channel is not None and after.channel is None:
        # VCから出た
        left_channel = before.channel
    elif (
        before.channel is not None
        and after.channel is not None
        and before.channel.id != after.channel.id
    ):
        # 別VCに移動
        left_channel = before.channel
        joined_channel = after.channel

    # 変化がないなら何もしない
    if joined_channel is None and left_channel is None:
        return

    # ログチャンネルを取得 or 作成
    log_channel = await get_or_create_log_channel(member)

    now = datetime.now(timezone.utc)
    key = (member.guild.id, member.id)

    # 退出処理（退出 or 移動元）
    leave_message = None
    if left_channel is not None:
        # 前回入室時刻が記録されていれば、滞在時間を計算
        if key in voice_join_times:
            joined_at = voice_join_times.pop(key)
            stay_time = now - joined_at
            stay_str = format_timedelta(stay_time)
            leave_message = (
                f"❌ {member.mention} が **{left_channel.name}** から退出しました。\n"
                f"　滞在時間: {stay_str}"
            )
        else:
            # Bot起動前から居たなどで記録がない場合
            leave_message = (
                f"❌ {member.mention} が **{left_channel.name}** から退出しました。\n"
                f"　滞在時間: 不明（入室時刻の記録なし）"
            )

    # 入室処理（入室 or 移動先）
    join_message = None
    if joined_channel is not None:
        # 新たに入室時刻を記録
        voice_join_times[key] = now
        join_message = (
            f"✅ {member.mention} が **{joined_channel.name}** に参加しました。"
        )

    # メッセージ送信順序
    # 移動の場合は「退出(滞在時間) → 入室」の順で書き込む
    if leave_message:
        await log_channel.send(leave_message)
    if join_message:
        await log_channel.send(join_message)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")


bot.run(TOKEN)
