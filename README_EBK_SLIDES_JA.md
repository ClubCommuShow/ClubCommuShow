# ClubCommuShow 画像・スライド管理

既存の名簿44人、ポスター52件、コンテンツ29件と権限・画像は保持しています。
このRepositoryは既存のmainルートをPagesへ公開する構成です。生成したdocs/ebk-room-mediaをルートebk-room-mediaにも同期し、同じWorkflowから公開します。

OpsのGitHub設定: RepositoryはClubCommuShow/ClubCommuShow、Branchはmain。
「画像・アルバム」でアルバム追加、画像ファイル/画像URLの一括追加・削除、登録済みサムネイル確認。
画像URLは実データをダウンロードし、ファイル共通で長辺2048px以下のPNGへ変換。
ポートレートのslot1/slot3/slot4は、その番号のPNG名で更新します。
Ops 0.4.33では各登録画像の「画像URLをコピー」も利用できます。

アルバム用画像はmedia/room-slides/<アルバム名>/に登録します。
1画像3フレーム・30fpsで同名動画を作り直します。サンプルは空のため画像待ちです。
ActionsのBuild EBK roster and slide albumsでbuild-videoとdeployの成功を待ってください。
一覧: https://clubcommushow.github.io/ClubCommuShow/ebk-room-media/
コピーしたURLはVRChat内のメディアボードへ手動入力・読込します。

## ClubCard

カード情報: data/clubcard_manifest.json。カード画像: images/clubcards/cards/。
カード一覧: https://clubcommushow.github.io/ClubCommuShow/clubcards/
63枚のカード番号・名前・有効状態・交換設定を原本から登録しています。
カード番号の末尾0=N、1=R、2=SR、3=SSR、4=UR、5=S。
標準排出ウェイトはN=2000、R=1000、SR=600、SSR=400、UR=40、S=3。
通常は上記の自動設定です。変更カードだけmanualRarityWeightOverride=trueとし、rarityOverride/weightOverrideを優先します。原本の00000と99999のS/3指定を保持しています。
自動へ戻す場合はフラグをfalseにして個別値を削除。末尾6〜9は自動割当がないため個別指定が必要です。
画像は原本PrefabのGUID参照を確認して登録。99999はCardImages/99999.pngで、カード裏面の参照にも同じ画像が設定されています。
原本ZIPの20021.pngだけCRCエラーのため、ユーザーが再送した20021.pngを登録しました。詳細はdata/clubcard_import_report.json。
ClubCardのVideoRoster動画取得・Ops専用カード情報編集・VRChat動的読込は後続対応です。今回の登録だけで既存ワールドのカードDBを置き換えません。
