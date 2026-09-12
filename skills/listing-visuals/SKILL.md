---
name: cross-border-listing-visuals
description: 生成跨境电商产品图的 AI 绘图提示词，并按平台规范做合规自查。覆盖亚马逊主图（纯白底）、场景图、功能说明图、尺寸对比图、A+ 图文模块，以及 TikTok/独立站的素材变体。当用户说「做产品主图 / 生成商品图 / 出一套详情页配图 / 做 A+ 内容 / 主图不合规怎么改 / 帮我写生图提示词」时使用。不用于：Listing 文字（用 cross-border-listing）、选品判断（用 cross-border-product-screening）、真实拍摄指导。
---

# 产品图生成与合规自查

跨境运营每天都要出图：新品主图、活动素材、A+ 模块、广告素材。
**图片不合规会直接导致 Listing 被下架或搜索降权**，而新手最常见的错误恰恰在主图上。

这个 skill 做两件事：
1. 按图片类型生成可直接用的**绘图提示词**
2. 出图后按平台规范**逐条自查**

> **适合在 Codex 里用** —— 它自带生图模型，提示词生成出来可以直接出图，
> 不用在两个工具之间来回倒。用法见项目里的 `CODEX使用指南.md`。

---

## 一、先分清五种图，用途完全不同

| 类型 | 位置 | 目的 | 能不能加文字 |
|---|---|---|---|
| **主图** | 搜索结果第一张 | 让人点进来 | **绝对不行** |
| **场景图** | 副图 2–3 位 | 让人想象在用 | 可以 |
| **功能图** | 副图 4–5 位 | 解释卖点 | 可以，且应该加 |
| **尺寸图** | 副图靠后 | 消除退货风险 | 必须加 |
| **A+ 模块** | 详情页中部 | 讲品牌与深度信息 | 可以 |

**新手最常犯的错**：把主图做成海报 —— 加大字、加促销角标、加边框。
**这在亚马逊会被判违规**，而且搜索结果里反而更不显眼（因为周围都是干净白底，你那张像广告）。

---

## 二、亚马逊主图硬规范

> ⚠️ 平台政策会变。下面是常见要求，**发布前请以目标站点后台的最新图片政策为准**。
> 这个 skill 不替代平台官方文档。

| 项 | 要求 |
|---|---|
| 背景 | **纯白 RGB (255,255,255)** |
| 商品占比 | 画面的 **85% 以上** |
| 尺寸 | 最长边 **1600px 以上**（才能启用鼠标悬停放大） |
| 格式 | JPEG / PNG / TIFF / GIF，**推荐 JPEG** |
| 禁止 | 文字、Logo 水印、边框、促销角标、非售卖的道具 |
| 禁止 | 插画、3D 渲染图（必须是实物图；部分类目有例外） |
| 禁止 | 裸露皮肤上的服装展示（服饰类另有规则） |
| 建议 | 商品完整入镜，不裁切；主体居中；轻微投影可以 |

**服饰类、图书类、食品类另有专门规则**，做这些类目前先查该类目的图片指南。

---

## 三、怎么用

### 输入格式

```json
{
  "product_name": "不锈钢真空保温杯",
  "category": "kitchen",
  "key_features": ["40oz 大容量", "手柄便携", "24 小时保温"],
  "target_market": "US",
  "image_type": "main",
  "brand_tone": "简洁实用",
  "notes": "杯身哑光黑，有提手和吸管"
}
```

`image_type` 取值：`main`（主图）/ `scene`（场景）/ `feature`（功能）/ `size`（尺寸）/ `aplus`（A+）

### 输出

一段可直接喂给生图模型的英文提示词 + 一份自查清单。

**提示词用英文** —— 主流生图模型对英文描述的服从度明显更高。

---

## 四、五类图的提示词模板

### 主图 main

```
Professional product photography of {product}, {material and color details},
centered composition, pure white seamless background RGB(255,255,255),
studio softbox lighting from upper left, subtle natural shadow beneath product,
product fills 85% of frame, sharp focus throughout, high detail,
commercial e-commerce catalog style, shot on medium format camera, 4K

Negative: text, watermark, logo, border, frame, props, hands, people,
gradient background, colored background, reflection overlay, promotional badge,
multiple products, cropped product
```

**必须带 negative 提示** —— 生图模型很容易自作主张加文字和装饰，那些正是违规项。

### 场景图 scene

```
Lifestyle photograph of {product} being used in {realistic scene},
natural window lighting, shallow depth of field, authentic everyday moment,
{target market} home interior style, warm color grading,
product clearly visible and in focus, editorial lifestyle photography

Negative: studio lighting, white background, staged stock photo feel,
distorted hands, extra fingers, unreadable text
```

**场景要贴目标市场。** 美国家庭的厨房和日本家庭的厨房长得不一样，
用错了会让人觉得"这不是给我用的"。

### 功能图 feature

```
Clean product feature illustration of {product},
close-up on {specific feature}, light neutral background (#F5F5F5),
soft studio lighting, large empty area on {left/right} for caption text,
macro detail shot, commercial photography

Negative: cluttered background, busy composition, text, watermark
```

**留白是刻意的** —— 文字后期加，不要让模型写字。**生图模型写出来的文字几乎必错**
（拼写错误、乱码），而错别字出现在 Listing 图上非常伤转化。

### 尺寸图 size

```
Product dimension reference photo of {product} next to {common reference object},
pure white background, side view, both objects fully visible,
even lighting, technical product photography, no distortion

Negative: text, arrows, measurement lines, perspective distortion
```

参照物选目标市场认得的：美国用手、咖啡杯、信用卡；日本用 500ml 宝特瓶。
**标注线和数字后期加**，别让模型画。

### A+ 模块 aplus

```
Wide banner composition featuring {product}, {brand tone} aesthetic,
generous negative space on {side} for copy, muted {color} palette,
premium lifestyle brand photography, 16:9 aspect ratio, soft diffused lighting

Negative: text, logo, busy background, low contrast
```

---

## 五、出图后自查清单

**每张图都要过一遍，尤其主图。**

主图：
- [ ] 背景是**纯白**吗？（用取色器点四角，必须是 255,255,255；肉眼看不出灰）
- [ ] 商品占画面 **85%** 以上吗？
- [ ] 有没有混进文字、水印、角标、边框？
- [ ] 有没有多余道具？（只能出现售卖的东西）
- [ ] 看起来像**实物照片**还是像渲染图/插画？
- [ ] 最长边 ≥1600px？

全部图：
- [ ] 商品和实物**一致**吗？（图文不符是投诉与退货的主要来源）
- [ ] 有没有暗示**医疗功效**？（"治疗""缓解疼痛""杀菌 99.9%"）
- [ ] 有没有**绝对化用语**？（"最好""第一""唯一"）
- [ ] 有没有别人的**品牌 Logo**？（包括参照物上的）
- [ ] 文字有没有拼写错误？（生图模型的文字几乎必错，**能不用就不用**）
- [ ] 人物形象符合目标市场吗？

---

## 六、这个 skill 的边界

- **不替你拍实物。** AI 生成图用于**方案验证、素材草稿、A+ 背景**是合适的；
  **主图强烈建议用真实拍摄**——图文不符会带来退货和投诉，得不偿失。
- **不判断平台最新政策。** 规范会变，发布前必须核对目标站点后台的图片政策。
- **不做图片编辑。** 输出的是提示词和自查清单，出图和修图在你自己的工具里做。
- **不生成含文字的图。** 模型写字几乎必错，文字一律后期加。
