import asyncio
import discord
from discord.ext import commands, tasks
import feedparser
import yt_dlp as youtube_dl
import os

Token = os.environ.get('DISCORD_TOKEN')

# Suppress noise about console usage from errors
youtube_dl.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)
        
class Music(commands.Cog): 
    def __init__(self, bot):  
        self.bot = bot 
        self.queue = asyncio.Queue()
        self.current = None
        self.is_playing = False

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context):
        print("someone send ping")
        await ctx.reply(f"pong! {round(self.bot.latency * 1000)}ms")
        
    @commands.command(aliases=['입장'])
    async def join(self, ctx):
        """음성 채널 입장 (= !입장)"""
        if ctx.author.voice and ctx.author.voice.channel:
            print("봇이 들어왔습니다.")
            channel = ctx.author.voice.channel
            # 이미 음성 채널에 입장한 경우 해당 채널로 이동
            if ctx.voice_client is not None:
                await ctx.voice_client.move_to(channel)
            else:
                # 봇이 음성 채널에 연결되지 않았다면
                await channel.connect()  # 음성 채널에 연결
            await ctx.send(f"{ctx.author}님이 {channel}에 입장했습니다.")
        else:
            await ctx.send("음성 채널에 유저가 존재하지 않습니다. 1명 이상 입장해 주세요.")

    @commands.command(aliases=['재생'])
    async def play(self, ctx, *, url):
        """대기열(큐)에 노래 추가 & 노래가 없으면 최근 노래 재생 (= !재생)"""
        async with ctx.typing():
            player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            if player is None:
                await ctx.send("노래를 가져오는데 문제 발생. URL을 확인해주세요.")
                return

            await self.queue.put(player)
            position = self.queue.qsize()
            await ctx.send(f'{player.title}, #{position}번째로 대기열에 추가.')

            # 현재 노래가 재생 중이 아니면 다음 곡 재생
            if not self.is_playing and not ctx.voice_client.is_paused():
                await self.play_next(ctx)

    async def play_next(self, ctx):
        if not self.queue.empty():
            self.current = await self.queue.get()
            self.is_playing = True
            ctx.voice_client.play(self.current, after=lambda e: self.bot.loop.create_task(self.play_next_after(ctx, e)))
            await ctx.send(f'Now playing: {self.current.title}')
        else:
            self.current = None
            self.is_playing = False

    async def play_next_after(self, ctx, error):
        if error:
            print(f'에러: {error}')
        self.is_playing = False
        await self.play_next(ctx)

    @commands.command(aliases=['스킵'])
    async def skip(self, ctx):
        """현재 재생중인 노래 스킵 (= !스킵)"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("현재 노래를 건너뜁니다.")
            await self.play_next(ctx)
        else:
            await ctx.send("현재 재생 중인 노래가 없습니다.")

    @commands.command(aliases=['퇴장'])
    async def stop(self, ctx):
        """음성 채널 퇴장 (= !퇴장)"""
        self.queue = asyncio.Queue()
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        await ctx.send("봇이 음성 채널을 나갑니다.")
        await ctx.voice_client.disconnect()

    @commands.command(aliases=['일시정지'])
    async def pause(self, ctx):
        ''' 음악을 일시정지 (= !일시정지)'''
        if ctx.voice_client.is_paused() or not ctx.voice_client.is_playing():
            await ctx.send("음악이 이미 일시 정지 중이거나 재생 중이지 않습니다.")
        else:
            ctx.voice_client.pause()
            await ctx.send("음악이 일시 정지되었습니다.")

    @commands.command(aliases=['다시재생'])
    async def resume(self, ctx):
        ''' 일시정지된 음악을 다시 재생 (= !다시재생)'''
        if ctx.voice_client.is_playing() or not ctx.voice_client.is_paused():
            await ctx.send("음악이 이미 재생 중이거나 재생할 음악이 존재하지 않습니다.")
        else:
            ctx.voice_client.resume()
            await ctx.send("음악이 다시 재생됩니다.")

    @commands.command(aliases=['플리'])
    async def playlist(self, ctx):
        """대기열(큐) 목록 출력 (= !플리)"""
        if not self.queue.empty():
            message = '플레이리스트:\n'
            temp_queue = list(self.queue._queue)
            for idx, player in enumerate(temp_queue, start=1):
                message += f'{idx}. {player.title}\n'
            await ctx.send(message)
        else:
            await ctx.send("대기열이 비어 있습니다. ")

    @commands.command(aliases=['삭제'])
    async def remove(self, ctx, index: int):
        """대기열(큐)에 있는 곡 삭제. 사용법: !remove 1 (= !삭제 1)"""
        if not self.queue.empty():
            temp_queue = list(self.queue._queue)  # Convert the queue to a list to access it
            if 0 < index <= len(temp_queue):
                removed = temp_queue.pop(index - 1)
                await ctx.send(f'삭제: {removed.title}')
                # Rebuild the queue
                self.queue = asyncio.Queue()
                for item in temp_queue:
                    await self.queue.put(item)
            else:
                await ctx.send("유효한 번호를 입력하세요.")
        else:
            await ctx.send("대기열이 비어 있습니다.")

    @play.before_invoke
    async def ensure_voice(self, ctx):
        if not (ctx.author.voice and ctx.author.voice.channel):
            await ctx.send("음성 채널에 유저가 없습니다. 유저가 음성 채널에 연결된 상태여야 합니다.")
            raise commands.CommandError("Author not connected to a voice channel.")
        elif ctx.voice_client is None:
            # 봇이 음성 채널에 연결되지 않은 경우
            if ctx.author.voice.channel:
                await ctx.author.voice.channel.connect()
            else:
                await ctx.send("음성 채널에 유저가 존재하지 않습니다.")
                raise commands.CommandError("Author not connected to a voice channel.")

# RSS 피드 확인 기능
class GameProfileNotifier(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_video_url = {
            "원신": None, "붕괴3rd": None, "스타레일": None, "명조": None, "웨이브": None, "블루아카이브": None
        }  # 각 게임마다 마지막으로 알림을 보낸 영상 URL을 저장
        self.enabled = True  # 알림 활성화 여부
        self.check_rss_feed.start()  # 주기적으로 피드를 체크하는 작업 시작

    @tasks.loop(minutes=10)  # 10분마다 실행
    async def check_rss_feed(self):
        if not self.enabled:
            return  # 알림이 비활성화되었으면 아무것도 안함

        # 각 게임에 대한 피드 URL과 알림 기능
        channels = {
            "원신": "https://www.youtube.com/@Genshinimpact_KR",
            "소녀전선 2": "https://www.youtube.com/@EXILIUMKR",
            "스타레일": "https://www.youtube.com/@Honkaistarrail_kr",
            "명조": "https://www.youtube.com/@WW_KR_Official",
            "블루아카이브": "https://www.youtube.com/@bluearchive_kr"
        }

        for game, rss_url in channels.items():
            feed = feedparser.parse(rss_url)

            if feed.entries:
                latest_entry = feed.entries[0]  # 가장 최신 항목
                video_url = latest_entry.link

                if video_url != self.last_video_url[game]:
                    channel = self.bot.get_channel(1352618480909684756)  # 알림을 보낼 채널 ID
                    await channel.send(f"{game}에서 새로운 영상이 업로드되었습니다!\n**{latest_entry.title}**\n{video_url}")
                    self.last_video_url[game] = video_url  # 마지막으로 보낸 영상 URL 업데이트

    @commands.command()
    async def 게임알림켰다(self, ctx):
        """게임 알림을 켭니다."""
        self.enabled = True
        await ctx.send("게임 프로필 알림이 활성화되었습니다.")

    @commands.command()
    async def 게임알림끈다(self, ctx):
        """게임 알림을 끕니다."""
        self.enabled = False
        await ctx.send("게임 프로필 알림이 비활성화되었습니다.")

# 봇 설정 및 실행 부분
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!"),
    description='봇 사용설명서',
    intents=intents,
)

# 봇이 커맨드를 처리할 수 있도록 on_message 이벤트 추가
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    await bot.process_commands(message)  # 커맨드를 처리할 수 있도록

@bot.event
async def on_ready():
    print(f'{bot.user} 봇 실행!! (ID: {bot.user.id})')

async def main():
    async with bot:
        await bot.add_cog(Music(bot))  # 음악봇 기능 추가
        await bot.add_cog(GameProfileNotifier(bot))  # 게임 프로필 알림 기능 추가
        await bot.start(Token)

asyncio.run(main())


