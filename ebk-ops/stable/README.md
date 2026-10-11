# EventBasicKit OPS stable channel

このディレクトリは EventBasicKit Windows OPS の安定版更新配布専用です。

公開するのは更新用の実行ファイルと検証用 manifest のみです。
EventBasicKit 本体、Unity フルキット、開発ソース、購入者向け有料データは配置しません。

Wizard は `manifest.json` の SHA-256 とサイズを確認し、検証に成功した場合だけ
`EBKOpsManager.exe` を更新に使用します。取得または検証に失敗した場合は、
EBK に同梱された payload へフォールバックします。
