# FTShare REST 接口

在「设置 → 数据源服务商」保存 FTShare API Key，再进入「数据源 → FTShare」。接口列表和 REST API 目录以两行标签展示官方分类和子分类，分类可以和套餐、关键词一起筛选。每个接口都标注免费版或基础版，可以单独启用或停用。数据源页的「搜索全部接口」可以跨平台查找并定位接口。

- 「API调试」支持按名称、路径、参数、业务类别和套餐查找接口。表单首次打开会预填官方 HTTP 示例和文档默认值；已保存的参数会替代示例值。
- 在数据源「操作 → 设置」中保存参数，列表里的「测试」会使用这组参数。REST API 目录中的临时修改只用于当次请求。
- API Key 由服务端加密存储，以 `FTSHARE_API_KEY` 请求头发往 FTShare。接口与来源总开关同时启用才能发送请求。基础版调用权限由 FTShare 账户决定。
- 目录覆盖[官方套餐总表](https://market.ft.tech/gateway/doc/p/pb8eizu3)中的免费版 168 项、基础版 57 项。多个 HTTP 路径合列一项时，在表单中选择路径。
- 「调用顺序」固定先用 FTShare、再用同花顺，仅对 A 股行情、A 股股票前复权日 K、A 股指数日 K 和 A 股交易日历生效。其他来源不参与主备。FTShare 港股交易日历独立调用；其余未配对的接口按官方分类展示。业务会根据请求生成参数，测试面板保存的示例只用于手动测试。

更新官方目录：

```sh
.venv/bin/python scripts/sync_ftshare_rest_catalog.py
.venv/bin/python -m pytest -q tests/test_ftshare_rest.py
```

同步工具按官方套餐列选择接口，从各接口的输入参数与 HTTP 示例生成本地目录。套餐数量变化会停止更新，待人工核对；Python SDK 专用参数不会进入 REST 表单。
