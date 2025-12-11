import os
import discord
from datetime import datetime, timezone

# ========== 環境変数から設定を取得 ==========
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID_STR = os.getenv("GUILD_ID")  # 例: "123456789012345678"

if TOKEN is None:
    raise RuntimeError("環境変数 DISCORD_TOKEN が設定されていません。Render の Environment に追加してください。")

if GUILD_ID_STR is None:
    raise RuntimeError("環境変数 GUILD_ID が設定されていません。Render の Environment に追加してください。")

GUILD_ID = int(GUILD_ID_STR)

LOG_CATEGORY_NAME = "VCログ"  # カテゴリ名
LOG_CHANNEL_NAME = "vc-log"   # ★ 全員共通で使うチャンネル名
# =====================================

# Intents 設定
intents = discord.Intents.default()
intents.members = True          # メンバー情報（ニックネーム取得などに必要）
intents.voice_states = True     # VC 入退出イベント
intents.guilds = True

client = discord.Client(intents=intents)

# (guild_id, member_id) -> join_time(UTC)
voice_join_times: dict[tuple[int, int], datetime] = {}


def format_timedelta(delta):
    """
    timedelta を「X時間Y分Z秒」みたいな日本語に整形
    """
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


async def get_or_create_log_channel(guild: discord.Guild) -> discord.TextChannel:
    """
    サーバー共通の VC ログ用テキストチャンネルを取得 or 作成する。

    ・カテゴリ名: LOG_CATEGORY_NAME (例: "VCログ")
    ・チャンネル名: LOG_CHANNEL_NAME (例: "vc-log")
    ・全員が閲覧できて、Bot だけが書き込めるイメージ
    """
    print(f"[DEBUG] get_or_create_log_channel in guild {guild.id}")

    # カテゴリを探す or 作る
    category = discord.utils.get(guild.categories, name=LOG_CATEGORY_NAME)
    if category is None:
        print("[DEBUG] VCログカテゴリがないので作成します")
        category = await guild.create_category(LOG_CATEGORY_NAME)

    # カテゴリ内に LOG_CHANNEL_NAME のチャンネルがあるか？
    channel = discord.utils.get(category.text_channels, name=LOG_CHANNEL_NAME)

    if channel is None:
        print(f"[DEBUG] ログ用テキストチャンネル {LOG_CHANNEL_NAME} がないので作成します")

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=False,  # 全員読み専用
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,  # Botだけ書き込める
            ),
        }

        channel = await guild.create_text_channel(
            name=LOG_CHANNEL_NAME,
            category=category,
            overwrites=overwrites,
            topic="全メンバー共通のVC入退出ログ",
        )
    else:
        print(f"[DEBUG] 既存のログチャンネル {LOG_CHANNEL_NAME} を使用します")

    return channel


@client.event
async def on_ready():
    print("===================================")
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print(f"監視対象の GUILD_ID: {GUILD_ID}")
    print("Bot がオンラインになりました")
    print("===================================")


@client.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
):
    """
    VCへの入室 / 退出 / 移動を検知して、共通ログチャンネルに記録する。
    退出時には滞在時間も書き込む。
    """

    guild = member.guild

    # 対象サーバー以外のイベントは無視
    if guild.id != GUILD_ID:
        return

    # Botはログ対象外
    if member.bot:
        return

    joined_channel = None
    left_channel = None

    # 実際に「チャンネルの入退出/移動」が起きたかだけを見る
    if before.channel is None and after.channel is not None:
        # 入室
        joined_channel = after.channel
    elif before.channel is not None and after.channel is None:
        # 退出
        left_channel = before.channel
    elif (
        before.channel is not None
        and after.channel is not None
        and before.channel.id != after.channel.id
    ):
        # 別VCに移動
        left_channel = before.channel
        joined_channel = after.channel
    else:
        # ミュート切り替えなど、チャンネルは変わっていない場合
        return

    # 共通ログチャンネル取得
    log_channel = await get_or_create_log_channel(guild)

    now = datetime.now(timezone.utc)
    key = (guild.id, member.id)

    # まず「退出側」のログ（移動時にも発生する）
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
            # Bot起動前から居たなどで記録が無い場合
            leave_message = (
                f"❌ {member.mention} が **{left_channel.name}** から退出しました。\n"
                f"　滞在時間: 不明（入室時刻の記録なし）"
            )

        print(f"[DEBUG] 退出ログ送信: {leave_message}")
        await log_channel.send(leave_message)

    # 次に「入室側」のログ
    if joined_channel is not None:
        voice_join_times[key] = now
        join_message = (
            f"✅ {member.mention} が **{joined_channel.name}** に参加しました。"
        )
        print(f"[DEBUG] 入室ログ送信: {join_message}")
        await log_channel.send(join_message)


# 実行
client.run(TOKEN)
