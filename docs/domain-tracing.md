# 会話支援の処理を追跡する

HTTP の request_id に加え、非同期の処理には conversation_id、run_id、generation、revision、文字起こしには session_id を付ける。ContextVar は asyncio task と to_thread に引き継がれる。本文ではなく ID で API、DB、プロバイダー呼出し、ブラウザの観測を関連付ける。

JSON ログは stderr に出る。外部の収集サービスを必須にせず、まず処理境界を明示して学べる実装にした。将来 OpenTelemetry を採用しても境界を再利用できる。現時点では単一 API プロセス用で、永続的なトレース保管や分散 traceparent の伝播は行わない。

| イベント | 意味 |
| --- | --- |
| suggestion.queued / queue_wait | 永続キューから処理開始まで |
| suggestion.prepare / generate / persist | 入力準備・エージェント全体・結果保存 |
| provider.responses | 個々の Responses 呼出し（最大3回、暗黙の再試行なし） |
| suggestion.search / search_results | 認可済みPDF検索・取得件数 |
| suggestion.failure | 保存した安全なエラーコードと再試行可否 |
| suggestion.sse_send | generation/revision の SSE 配信 |
| transcription.provider_connect / first_audio | 文字起こし接続と最初の音声受信 |
| transcription.partial / final / persist_final / ws_send | 暫定・確定・保存・配信 |
| transcription.failure / closed | 固定エラーコード・終了状態 |
| browser.*.paint_opportunity | 受信から React commit 後の描画機会まで（クライアント自己申告） |
| suggestion.created_to_browser_ack | run作成からブラウザ観測POST到着まで（サーバー時計同士） |

ブラウザ観測は認証と組織認可、run/session の会話一致を検証する。投稿は数値・UUID・決められた種類だけで、本文・資料抜粋・音声・Cookie・APIキー・生の例外はログへ渡さない。投稿失敗は利用中の画面状態を変更しない。ユーザーごとに毎分120件まで、カウンターも最大4096ユーザーに制限し、追加のドメインDB検索の前に超過を拒否する。分散運用時は共有レート制限に置き換える。

## 遅延の読み方

- first_partial_latency は最初の音声受信から最初の暫定文字起こしまで。発話開始前の無音と、プロバイダーの音声区切りの待ちを含み得る。各発話の純粋なASR時間ではない。
- created_to_browser_ack は入力確定・run作成から生成、配信、ブラウザ処理、観測の戻り通信までを含む上限側の指標。正確な描画時刻とは区別する。
- receive_to_paint_ms はブラウザ内の performance.now で計測する。2回のrequestAnimationFrameは描画機会を示し、人が画面を見たことの証明ではない。非表示画面とキャンセルされた会話、GET/SSEの復元snapshotは提案のlive計測から除く。
- 暫定文字起こしはセッション最初の1回と確定イベントを計測する。大量の音声チャンクを1件ずつログやHTTPへ送ることは避ける。

`uv run --directory backend python -m signal_api.evaluate_traces < api.log` で末尾10000件の p95 と目標（暫定1000ms、提案5000ms）を集計する。未計測は unmeasured とし、成功扱いしない。

モック時計800ms/3500msのテストは測定の計算を検証するだけで、実性能を保証しない。実OpenAI+架空PDFの提案生成ではDB作成〜完了6.67秒を確認済み（ブラウザ表示までの測定ではなく、2〜5秒目標の達成ではない）。実Google Meetと物理マイクを通した遅延は未検証。実測時はブラウザ、音声取得方法、データ、モデル、サンプル数を別途記録する。

承認・人への引継ぎのイベント統合はそれぞれの機能実装後に追加する（Issue #38 / #39）。Issue #40 はその統合まで未完了。
