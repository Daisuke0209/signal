# 確定発言から自動提案へ

文字起こしの final と手入力の保存トランザクションで、入力発言を固定した
queued 実行も作成する。commit 後にイベントループへ通知し、ポーリングせず生成を
開始する。partial は保存・生成のトリガーにしない。同じ文字起こし final の再送も
新しい生成を作らない。

## 責任の分離

- `suggestion_agent.py`: OpenAI Responses API と最大2回の読み取り専用検索。
  モデル・HTTP・検索・状態通知を差し替えられる。会話と検索結果は非信頼データとして
  扱い、実際に検索した根拠IDだけを出力で許可する。生成と検索全体に時間制限を設ける。
- `suggestion_runtime.py`: 世代の選択、同時実行数4、古い生成の取消、DBへの公開。
  外部API待機中にDBロックや接続を保持しない。会話が終了した場合や入力発言が
  進んだ場合は、古い結果を保存せず interrupted にする。
- `suggestion_events.py` と `suggestion_stream.py`: SSEへのpush。
  初期snapshotと状態変更を同じ `{conversation_id, latest_run}` 形式で返す。
  クライアントは `(generation, revision)` の順序で古いデータを除外する。
  `phase` は running 時の generating / searching、それ以外は null。
- `suggestions.py`: 実行と結果の永続化・認可付き取得。根拠は資料ID・資料名・
  ページ番号・抜粋をスナップショットとして保存し、再読込でも同じ根拠を表示する。

資料が利用できないときは検索ツールを渡さず、その状態をモデルへ明示する。
検索はサーバーが固定した組織内の ready 資料だけを対象とする。会話ごとの資料選択は
#46 のサービス境界で追加する。自由なURL取得・メール送信などの副作用ツールは持たない。

## 障害と運用上の境界

この版は **APIプロセス1つ** で動かす。DBを永続キューにし、通知と購読だけをメモリで
扱う方式はローカル用途で構造が明確になる。複数workerへ拡張するときは共有brokerと
job claim/leaseが必要になる。起動時に queued を再開し、running は interrupted にする。
commit後の通知前にプロセスが停止しても、次回起動でqueuedを回収できる。

SSEは最大1時間で再接続し、最大32件のバッファを超えた古い通知を捨てる。
セッション期限・ログアウト・組織所属を2秒ごと及び送信直前に再検証し、失効時は
`access_revoked` を送って閉じる。待機中にDB接続を保持しない。

失敗は固定コード provider_unavailable / timeout / generation_failed / interrupted
で保存する。APIキー、会話本文、PDF本文、プロバイダーの例外本文をログへ出さない。
新しい確定発言で次の生成を開始する。自動の無制限リトライは行わない。

## 有効化と検証

`SUGGESTIONS_ENABLED=false` が既定値。会話テキストと登録PDFの検索抜粋をOpenAI APIへ
送ることについて利用者が承認した後で true にする。キーはサーバーの環境変数だけに置く。
設定しただけではブラウザへキーは公開されない。

モデル/ツールの単体テストとPostgreSQL統合テストは、明示的に注入したモックを使用する。
イベント順序、永続化、古い結果の拒否、final再送の冪等性、所属取り消し時のSSE切断を検証する。
実通話での2〜5秒の体感遅延は別途計測する必要がある。

参照: [Function calling](https://developers.openai.com/api/docs/guides/function-calling)、
[Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
