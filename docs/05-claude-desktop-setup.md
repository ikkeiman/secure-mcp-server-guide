# 05. Claude Desktop への設定(検証済みの事実のみ)

この章は、公式ドキュメント(参考資料 [D1][D2][D3])で確認できた内容だけを書いています。
確認日は 2026-11-08 です。UI の文言や場所はバージョンで変わるため、食い違ったら公式ドキュメントを優先してください。

## 設定ファイル `claude_desktop_config.json`

| OS | パス |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json`(公式ドキュメントに記載あり。Linux 版アプリの提供状況は要確認) |

開き方: メニューバーの Claude メニューから「Settings...」→「Developer」タブ →「Edit Config」。

書式: トップレベルの `mcpServers` オブジェクトに、サーバー名をキーとして `command`・`args`、必要なら `env` を書きます。

```json
{
  "mcpServers": {
    "notes": {
      "command": "/絶対パス/uv",
      "args": ["--directory", "/絶対パス/secure-mcp-server-guide", "run", "reference/server.py"],
      "env": { "NOTES_ROOT": "/絶対パス/読ませてよいフォルダ" }
    }
  }
}
```

保存後は **Claude Desktop を完全に終了して起動し直す**必要があります。サーバーはアプリ起動時に起動されます。

## 起動まわりで公式ドキュメントが注意している点

- **パスは絶対パスで書く**。「設定から起動されたサーバーの作業ディレクトリは未定義(macOS では `/` など)になりうる」ため、
  設定ファイルや `.env` の参照も絶対パスにする([D3])
- **環境変数は一部しか引き継がれない**。「stdio で起動された MCP サーバーは、環境変数の限られた一部しか自動では継承しない」。
  必要な変数は `env` キーで明示する([D3])。ただし秘密情報を書くのは避ける([02](02-common-mistakes.md) M4)
- **`uv` はフルパスが必要な場合がある**。公式チュートリアルは「`command` には `uv` 実行ファイルのフルパスを入れる必要があるかもしれない」とし、
  `which uv`(macOS/Linux)/ `where uv`(Windows)で確認するよう案内している([D2])
- **stdout に書かない**。「ローカル MCP サーバーは stdout にログを出してはならない。プロトコルの動作を妨げる」。
  stderr への出力はホストが自動で取り込む([D3])

## `uv` / `uvx` で起動する場合の注意

- 公式チュートリアルの起動形は `uv --directory /絶対パス/プロジェクト run server.py`([D2])。
  プロジェクトに `uv.lock` があれば、依存の版が固定されたまま起動できます。本リポジトリの参照実装はこの形を推奨します
- `uvx` は `uv tool run` の別名で、ツールを一時的な環境に入れて実行します([U1])。
  つまり **設定に `uvx パッケージ名` と書くと、起動のたびにレジストリからコードを取得して実行**することになります。
  使うなら出所を確認し、版を固定してください([01](01-threat-model.md) T5)
- `npx -y パッケージ名` も同様に「取得して実行」です。公式の例として存在する形式ですが、何を取ってくるかは利用者の責任です

## ログの場所(確認できた範囲)

| OS | ディレクトリ |
|---|---|
| macOS | `~/Library/Logs/Claude` |
| Windows | `%APPDATA%\Claude\logs` |
| Linux | `~/.config/Claude/logs` |

- `mcp.log`: MCP 接続全般のログ
- `mcp-server-<サーバー名>.log`: そのサーバーの **stderr 出力**

macOS での追いかけ方の例(公式ドキュメント記載): `tail -n 20 -F ~/Library/Logs/Claude/mcp*.log`

ここに**本文や秘密情報を書かない**のがサーバー側の責任です([02](02-common-mistakes.md) M8)。

## 配布するなら: MCP Bundle(`.mcpb`)

設定ファイルを手で編集してもらう代わりに、サーバー一式と `manifest.json` を zip にした **MCP Bundle(`.mcpb`、旧称 Desktop Extensions / `.dxt`)** を
Claude Desktop にドラッグ&ドロップやダブルクリックでインストールしてもらう方法があります([C3][C4])。

- サーバーは利用者のマシン上で stdio で動く(仕組みは設定ファイル方式と同じ)
- `manifest.json` の `user_config` で設定項目を宣言でき、`"sensitive": true` を付けた値は OS の安全な保管領域に保存される([C1][C3])
- Team / Enterprise では管理者が拡張機能の許可・ブロックを制御できる([C1][C2])
- 公式ドキュメントは Node.js を強く推奨している(Claude Desktop に同梱されるため利用者側のランタイム不要)。Python サーバーも「サポート対象」とされるが、
  利用者側に Python 環境が必要になる点は要確認([C3])

本リポジトリの参照実装は学習用のため、`.mcpb` 化はしていません([README](../README.md#やっていないこと制約))。

## リモートサーバーについて

Claude には、ローカル起動とは別に **「カスタムコネクタ」として HTTPS の MCP サーバー URL を登録する**方法もあります(Settings → Connectors)。
公式ドキュメントは「信頼できる組織のサーバーにだけ接続する」「認証時に要求される権限を確認する」「『常に許可』は信頼できるサーバーにだけ使う」と注意しています([C2][D4])。
本資料の対象外ですが、[03](03-options.md) 案 D を組織で採る場合の入口になります。
