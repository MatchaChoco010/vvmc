# vvmc

VoiceVox + Markov Chain。マルコフ連鎖で生成し続けるテキストを VoiceVox で延々と読み上げる Web アプリ。

## 利用シーン / 制約

- **LAN 内アクセス前提**。開発機で `docker compose up` し、同一 LAN のスマホ等からアクセスする。
  - サーバは必ず `0.0.0.0` にバインドする(`localhost` 固定にしない)。
  - HTTPS は前提にしない(LAN 用途)。Service Worker 等の HTTPS 必須機能は避ける。
- 認証なし。社内/家庭内 LAN を信頼境界とする。

## ユーザフロー / UI

- VoiceVox の話者(speaker)を選択する UI(`/speakers` から取得した一覧)。
- **再生開始ボタン**:押すと再生開始。再生中は同じボタンが**一時停止ボタン**に変わる(トグル)。
- **リセットボタン**:現在の生成・再生をクリアし、マルコフ連鎖の状態も初期化する。
- **流れる字幕画面**:読み上げ中の文字がスクロールして表示される。
  - **DOM に保持するのは画面に見える範囲のみ**。スクロールアウトした文字は DOM から削除する(履歴は持たない)。
  - 仮想スクロールではなく、文字単位で append / shift する素朴な実装で良い(長時間動作でメモリリークしないことが要件)。

## 生成・読み上げの動作

- マルコフ連鎖はその場で 1 文ずつ生成 → VoiceVox で合成 → 再生、の繰り返し。
- 先読みでバッファを 1〜2 文確保し、再生が途切れないようにする。
- 一時停止中は新規生成も止める(無駄な合成を避ける)。
- リセットでバッファ・再生キュー・字幕表示を全部捨てる。

## マルコフ連鎖

- **コーパス = フォルダ**。`corpus/<name>/` 配下の `.txt` を全部まとめて
  1 つの MarkovModel を学習する。フォルダごとに独立したチェインができる。
  - 配置場所: `corpus/` ディレクトリ(リポジトリ管理外、`.gitignore` 対象)。
  - 起動時に `corpus/` の各サブディレクトリをスキャンしてモデル構築。
  - 例: `corpus/akutagawa/*.txt` と `corpus/souseki/*.txt` があれば
    "akutagawa" / "souseki" の 2 モデルが作られる。
  - `corpus/` 直下に置いた `.txt` は無視する(必ずサブディレクトリに入れる)。
- UI では複数のコーパスから 1 つ選んで切り替えできる。`/api/corpora` で一覧を返す。
- テスト用に**青空文庫**のテキストを使う。
  - 青空文庫テキスト特有の前処理が必要(タイトル/著者/記号についての注意書きを
    `----` 区切り線 2 本まで含めて落とす、ルビ `《》`、ルビ開始指定 `｜`、
    入力者注 `［＃...］`、外字注 `※［＃...］`、底本以降の切り捨て)。
    前処理は `backend/app/preprocess.py` に集約する。
- 日本語の分かち書きには **fugashi + unidic-lite** を使用(pure-Python に近く apt パッケージ不要)。
- N-gram は 2-gram(bigram)を既定とし、文末記号で文を区切る。

## 技術スタック(暫定)

| レイヤ | 採用 | 備考 |
|---|---|---|
| VoiceVox | `voicevox/voicevox_engine:cpu-latest` | Docker 公式イメージ。GPU 版は使わない |
| バックエンド | Python 3.12 + FastAPI + uvicorn | 形態素解析ライブラリの都合で Python |
| 形態素解析 | fugashi + unidic-lite | MeCab バインディング。辞書同梱で楽 |
| VoiceVox クライアント | httpx (async) | `audio_query` → `synthesis` の 2 段呼び出し |
| フロントエンド | Vite + React + TypeScript | 小規模なので素の React で十分 |
| 状態管理 | React の `useState` / `useReducer` のみ | Redux 等は導入しない |
| 音声再生 | Web Audio API (`AudioContext` + `decodeAudioData`) | `<audio>` タグだとギャップが出やすい |
| 配信(本番) | バックエンドの FastAPI が静的ファイルを配信 | nginx は使わない(構成簡素化) |

これらは初期判断。ハマりどころが出たら CLAUDE.md ごと差し替える。

## ディレクトリ構成(想定)

```
vvmc/
├── .devcontainer/         # 開発用コンテナ定義
├── backend/               # FastAPI アプリ
│   ├── app/
│   │   ├── main.py        # ASGI エントリ
│   │   ├── markov.py      # マルコフ連鎖
│   │   ├── voicevox.py    # VoiceVox クライアント
│   │   └── preprocess.py  # 青空文庫等の前処理
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/              # Vite + React
│   ├── src/
│   ├── package.json
│   └── Dockerfile         # 本番ビルド用(マルチステージで static 出力)
├── corpus/                # 学習元テキスト(.gitignore)
│   ├── <name1>/*.txt      # コーパスごとにフォルダを掘る(= 1 つのチェイン)
│   └── <name2>/*.txt
├── docker-compose.yml     # 本番(LAN 配信)用
├── docker-compose.dev.yml # 開発用(hot reload)
└── README.md
```

## ポート

| サービス | ポート | 用途 |
|---|---|---|
| backend | 8000 | FastAPI(API + 静的ファイル配信) |
| frontend (dev) | 5173 | Vite dev server。本番は使わない |
| voicevox | 50021 | VoiceVox engine(LAN に晒さない、内部ネットワークのみ) |

## API 設計(暫定)

- `GET /api/speakers` … VoiceVox の話者一覧をパススルー
- `GET /api/corpora` … 学習済みコーパス名の一覧(サブディレクトリ名)
- `POST /api/sentence` `{ speaker_id, corpus_name }` → `{ text: string, audio: base64 wav, mora: [...] }`
  - 1 リクエスト = 1 文。クライアントが連続して叩いてバッファを埋める。
  - `mora` は文字と再生時間のマッピング(字幕同期用)。VoiceVox の `audio_query` の `accent_phrases` から組み立てる。
- `POST /api/reset` `{ corpus_name? }` … 指定コーパスの乱数状態を初期化。省略時は全コーパス。

字幕同期は VoiceVox の `audio_query` が返す mora 単位の長さ情報をそのまま使う。クライアント側で時刻を見て文字を流す。

## 開発ワークフロー

devcontainer の中で作業する想定。

```bash
# 開発起動(hot reload あり)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up

# スマホからのアクセス確認
# http://<開発機の LAN IP>:8000
```

- `corpus/<name>/*.txt` にコーパスを置いてから起動する。空だと UI の一覧も空になる。
- VoiceVox エンジンの初回 pull は数 GB あるので注意。
- フロントエンドは dev サーバ(5173)で開発し、API は backend(8000)に proxy する。Vite の `server.proxy` 設定を使う。

## やらないこと

- ユーザ認証 / マルチテナント
- 読み上げ履歴の永続化(明示的要件で「履歴を持たない」)
- HTTPS / 公開インターネット配信
- 複数クライアントの同期再生(各自のブラウザで独立に動く)

## メンテ規約

- このファイル(CLAUDE.md)は「コードを読めば分かること」を書かない。**設計判断の理由**と**外部から見えない制約**だけ書く。
- 技術選定を変えたら表を更新する。古い選択肢を残さない。
