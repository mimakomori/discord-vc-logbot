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
LOG_CATEGORY_NAME = "VCログ"
# =====================================

# Intents 設定
intents = discord.Intents.default()
intents.members = True          # メンバー情報（ニックネーム取得に必要）
intents.voice_states = True     # VC 入退出イベント
intents.guilds = True

# commands.Bot ではなく、シンプルな Client で十分
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


async def get_or_create_log_channel(member: discord.Member) -> discord.TextChannel:
    """
    メンバーに対応する VC ログ用テキストチャンネルを取得 or 作成する。

    ・カテゴリ名: LOG_CATEGORY_NAME (例: "VCログ")
    ・チャンネル名: その人が「最初に VC に入室したときのサーバーニックネーム」
      → 2回目以降は同じチャンネルを使い続ける
    """
    guild = member.guild
    print(f"[DEBUG] get_or_create_log_channel for member {member} in guild {guild.id}")

    # カテゴリを探す or 作る
    category = discord.utils.get(guild.categories, name=LOG_CATEGORY_NAME)
    if category is None:
        print("[DEBUG] VCログカテゴリがないので作成します")
        category = await guild.create_category(LOG_CATEGORY_NAME)

    # ★ チャンネル名 = 最初に入室したときのサーバーニックネーム
    # member.display_name は「サーバーニックネーム or ユーザー名」
    nickname = member.display_name
    channel_name = nickname

    # 既にその名前のチャンネルがカテゴリ内に存在するか？
    channel = discord.utils.get(category.text_channels, name=channel_name)

    if channel is None:
        print(f"[DEBUG] ログ用テキストチャンネル {channel_name} がないので作成します")

        # 権限設定
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                read_messages=False
            ),  # 他の人には見せない
            member: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=False,  # ログ専用にしたいので書き込み不可
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
            ),
        }

        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"{member.display_name} のVCログ（初回ニックネーム固定）",
        )
    else:
        print(f"[DEBUG] 既存のログチャンネル {channel_name} を使用します")

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
    VCへの入室 / 退出 / 移動を検知して、ユーザーごとのログチャンネルに記録する。
    退出時には滞在時間も書き込む。
    """

    # 対象サーバー以外のイベントは無視
    if member.guild.id != GUILD_ID:
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

    # ここまで来たら「VCチャンネルの変化」が確定しているのでログ処理
    log_channel = await get_or_create_log_channel(member)

    now = datetime.now(timezone.utc)
    key = (member.guild.id, member.id)

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
