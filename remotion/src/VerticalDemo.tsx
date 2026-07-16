import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  Video,
} from "remotion";
import type { RenderShot, SubtitleCue, TimelineProps } from "./types";

const clamp = (value: number) => Math.max(0, Math.min(1, value));
const easeOut = (value: number) => 1 - Math.pow(1 - clamp(value), 3);
const easeInOut = (value: number) => {
  const progress = clamp(value);
  return progress < 0.5 ? 4 * progress ** 3 : 1 - Math.pow(-2 * progress + 2, 3) / 2;
};

type Rect = {x: number; y: number; w: number; h: number};
const safeRect = (props: TimelineProps, key: "content" | "critical" | "subtitle_top" | "subtitle_lower", fallback: Rect): Rect =>
  props.style?.safe_area?.[key] ?? fallback;

const Grid = () => (
  <AbsoluteFill
    style={{
      backgroundColor: "#070a0e",
      backgroundImage:
        "linear-gradient(rgba(53,62,74,.45) 1px, transparent 1px), linear-gradient(90deg, rgba(53,62,74,.45) 1px, transparent 1px), linear-gradient(rgba(25,31,38,.72) 1px, transparent 1px), linear-gradient(90deg, rgba(25,31,38,.72) 1px, transparent 1px)",
      backgroundSize: "128px 128px, 128px 128px, 32px 32px, 32px 32px",
    }}
  />
);

const assetUrl = (assetId: string, assets: TimelineProps["assets"]) => {
  const asset = assets.find((item) => item.asset_id === assetId);
  if (!asset) throw new Error(`Unknown render asset: ${assetId}`);
  return staticFile(asset.path);
};

const assetFor = (assetId: string, assets: TimelineProps["assets"]) => {
  const asset = assets.find((item) => item.asset_id === assetId);
  if (!asset) throw new Error(`Unknown render asset: ${assetId}`);
  return asset;
};

const Media: React.FC<{
  assetId: string;
  assets: TimelineProps["assets"];
  style: React.CSSProperties;
}> = ({assetId, assets, style}) => {
  const asset = assetFor(assetId, assets);
  const src = assetUrl(assetId, assets);
  return asset.media_type === "video"
    ? <Video src={src} style={style} muted loop />
    : <Img src={src} style={style} />;
};

const sequenceAsset = (shot: RenderShot, frame: number) => {
  const sequence = shot.parameter_sequence;
  if (!sequence) return { assetId: shot.asset_bindings.primary ?? Object.values(shot.asset_bindings)[0], opacity: 1 };
  return { assetId: sequence.base_asset_id, opacity: 1 };
};

const ParameterCallout: React.FC<{shot: RenderShot}> = ({shot}) => {
  const frame = useCurrentFrame();
  const sequence = shot.parameter_sequence;
  if (!sequence) return null;
  const revealFrames = Math.max(1, sequence.callout_reveal_frames ?? 10);
  const reveal = easeOut(clamp((frame - sequence.stage_frame) / revealFrames));
  if (reveal <= 0) return null;
  return <div style={{position: "absolute", right: "6%", top: "43%", width: "43%", height: "30%", opacity: reveal, transform: `translateY(${(1 - reveal) * 22}px) rotate(-4deg)`, transformOrigin: "center", pointerEvents: "none"}}>
    <div style={{position: "absolute", right: 0, top: 0, color: "#ffd629", fontFamily: "Noto Sans CJK SC, Microsoft YaHei, sans-serif", fontWeight: 950, fontSize: 64, lineHeight: 1.04, textAlign: "center", textShadow: "3px 4px 0 #111, -2px -2px 0 #111"}}>{sequence.callout_text ?? "填写必填项"}</div>
  </div>;
};

const fittedStage = (
  assetId: string,
  props: TimelineProps,
  content: Rect,
  maxHeightRatio = 0.9,
) => {
  const asset = assetFor(assetId, props.assets);
  const ratio = Math.max(0.05, asset.width / asset.height);
  const maxWidth = content.w;
  const maxHeight = content.h * maxHeightRatio;
  const width = Math.min(maxWidth, maxHeight * ratio);
  const height = width / ratio;
  return {
    left: content.x + (content.w - width) / 2,
    top: content.y + (content.h - height) / 2,
    width,
    height,
  };
};

const OverlayImage: React.FC<{ shot: RenderShot; props: TimelineProps }> = ({ shot, props }) => {
  const frame = useCurrentFrame();
  const layout = shot.overlay_layout;
  if (!layout) throw new Error(`Overlay shot ${shot.shot_id} has no layout`);
  const selected = sequenceAsset(shot, frame);
  const content = safeRect(props, "content", {x: 100, y: 186, w: 856, h: 1536});
  const local = Math.max(0, frame - shot.start_frame);
  const duration = Math.max(1, shot.end_frame - shot.start_frame);
  const progress = clamp(local / duration);
  const pulse = shot.motion === "brand_breath" ? 1 + Math.sin(local / 10) * 0.018 : 1;
  const reveal = shot.motion === "fade_in" ? clamp(local / 8) : 1;
  return <div style={{
    position: "absolute",
    left: content.x + layout.x * content.w,
    top: content.y + layout.y * content.h,
    width: layout.w * content.w,
    height: layout.h * content.h,
    opacity: layout.opacity * reveal,
    zIndex: layout.z_index,
    overflow: "hidden",
    borderRadius: 20,
    transform: `scale(${pulse}) ${shot.motion === "scale_in" ? `scale(${0.88 + easeOut(progress) * 0.12})` : ""}`,
    transformOrigin: "center center",
    boxShadow: "0 14px 30px rgba(0,0,0,.42)",
  }}>
    <Media assetId={selected.assetId} assets={props.assets} style={{width: "100%", height: "100%", objectFit: layout.fit === "cover" ? "cover" : "contain"}} />
  </div>;
};

const MotionImage: React.FC<{ shot: RenderShot; props: TimelineProps }> = ({ shot, props }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const local = Math.max(0, frame - shot.start_frame);
  const duration = Math.max(1, shot.end_frame - shot.start_frame);
  const progress = clamp(local / duration);
  const selected = sequenceAsset(shot, frame);
  if (shot.track === "overlay") return <OverlayImage shot={shot} props={props} />;
  if (shot.template === "editor_interaction") {
    return <EditorInteraction shot={shot} props={props} />;
  }
  if (shot.motion === "full_bleed_to_safe_card") {
    return <FullBleedToSafeCard assetId={selected.assetId} shot={shot} props={props} />;
  }
  if (shot.motion === "page_turn_3d") {
    return <PageTurnCard assetId={selected.assetId} shot={shot} props={props} />;
  }
  if (shot.motion === "card_flip_3d") {
    return <CardFlip3D assetId={selected.assetId} shot={shot} props={props} />;
  }
  if (shot.motion === "paper_curl_flip") {
    return <PaperCurlFlip assetId={selected.assetId} shot={shot} props={props} />;
  }
  if (shot.motion === "slide_gallery") {
    return <SlideGallery shot={shot} props={props} />;
  }
  if (shot.motion === "card_stack") {
    return <CardStack shot={shot} props={props} />;
  }
  if (shot.motion === "grid_reveal") {
    return <GridRevealCard assetIds={Object.values(shot.asset_bindings)} shot={shot} props={props} />;
  }
  const previous = null;
  const entrance = spring({ frame: local, fps, config: { damping: 200, stiffness: 110, mass: 0.8 } });
  const isDense = shot.template === "ui_params_focus";
  const isEntry = shot.template === "ui_feature_entry";
  const isEditor = shot.scene_kind === "editor_workspace";
  const isResult = shot.template === "result_showcase";
  const isPanScan = shot.motion === "image_pan_scan" || shot.motion === "vertical_scroll";
  const sourceAsset = props.assets.find((asset) => asset.asset_id === selected.assetId);
  const content = safeRect(props, "content", {x: 100, y: 186, w: 856, h: 1536});
  const fitted = isDense
    ? {left: content.x, top: content.y + content.h * 0.03, width: content.w, height: content.h * 0.94}
    : fittedStage(selected.assetId, props, content, isEditor ? 0.9 : 0.86);
  const stageWidth = isPanScan ? content.w : fitted.width;
  const stageHeight = isPanScan ? Math.min(content.h, Math.round(content.h * 0.84)) : fitted.height;
  const stageRatio = stageWidth / stageHeight;
  const sourceRatio = sourceAsset ? sourceAsset.width / sourceAsset.height : stageRatio;
  // Fit-contain is the opening state. This is the minimum scale that turns a
  // full horizontal image into an edge-to-edge detail view inside the portrait stage.
  const coverScale = sourceRatio > stageRatio ? sourceRatio / stageRatio : stageRatio / sourceRatio;
  const scanTargetScale = Math.min(2.85, Math.max(1.45, coverScale * 1.08));
  const scanBaseWidth = sourceRatio > stageRatio ? stageWidth : stageHeight * sourceRatio;
  const scanBaseHeight = sourceRatio > stageRatio ? stageWidth / sourceRatio : stageHeight;
  const pan = easeOut(progress);
  let scale = 1;
  let x = 0;
  let y = 0;
  let rotateY = 0;
  let opacity = 1;
  if (shot.motion === "fade_in" || shot.motion === "result_reveal" || shot.motion === "grid_reveal") opacity = clamp(local / 8);
  if (shot.motion === "scale_in") scale = isDense ? 0.97 + entrance * 0.035 : 0.86 + entrance * 0.16;
  if (shot.motion === "scale_out") scale = 1.06 - entrance * 0.06;
  if (shot.motion === "detail_push_in" || shot.motion === "film_strip") {
    scale = 1.14 + 0.28 * easeOut(Math.min(1, progress / 0.72));
    x = isEntry ? -8 + 5 * pan : 0;
    y = isEntry ? -5 + 3 * pan : 0;
  }
  if (shot.motion === "brand_breath") {
    scale = 1 + Math.sin(local / 10) * 0.018;
    y = Math.sin(local / 14) * -1.4;
  }
  // A virtual camera starts by showing the entire source, then studies it.
  // The movement stays inside the clipped card, so it cannot reveal blank canvas.
  // Hold the whole image briefly, then emulate a deliberate hand-held
  // inspection: zoom -> look left/up -> sweep right -> settle left/down.
  const zoomIn = easeOut(clamp((progress - 0.12) / 0.36));
  const scanProgress = clamp((progress - 0.48) / 0.52);
  // These are image offsets, so the camera travels in the opposite direction.
  const scanXLimit = Math.max(0, (scanBaseWidth * scanTargetScale - stageWidth) / 2);
  const scanYLimit = Math.max(0, (scanBaseHeight * scanTargetScale - stageHeight) / 2);
  const scanX = interpolate(scanProgress, [0, 0.22, 0.62, 1], [0, scanXLimit * 0.88, -scanXLimit * 0.96, scanXLimit * 0.72]);
  const scanY = interpolate(scanProgress, [0, 0.22, 0.62, 1], [0, scanYLimit * 0.86, scanYLimit * 0.46, -scanYLimit * 0.9]);
  const imageTransform = isPanScan
    ? `translate(${scanX}px, ${scanY}px) scale(${1 + (scanTargetScale - 1) * zoomIn})`
    : undefined;
  const cardStyle: React.CSSProperties = {
    position: "absolute",
    left: isPanScan ? content.x : fitted.left,
    top: isPanScan ? content.y + (content.h - stageHeight) / 2 : fitted.top,
    width: stageWidth,
    height: stageHeight,
    borderRadius: 26,
    overflow: "hidden",
    boxShadow: "10px 22px 34px rgba(0,0,0,.54)",
    opacity,
    transform: `perspective(1800px) translate(${x}%, ${y}%) scale(${scale}) rotateY(${rotateY}deg)`,
    transformOrigin: "center center",
    backgroundColor: "transparent",
  };
  const imageStyle: React.CSSProperties = isPanScan
    ? {
        position: "absolute",
        left: (stageWidth - scanBaseWidth) / 2,
        top: (stageHeight - scanBaseHeight) / 2,
        width: scanBaseWidth,
        height: scanBaseHeight,
        objectFit: "fill",
        transform: imageTransform,
        transformOrigin: "center center",
      }
    : {
        width: "100%",
        height: "100%",
        objectFit: "fill",
      };
  return (
    <AbsoluteFill style={{ perspective: 1800 }}>
      <div style={cardStyle}>
        <Media assetId={selected.assetId} assets={props.assets} style={{...imageStyle, opacity: selected.opacity}} />
        {previous ? <Media assetId={previous} assets={props.assets} style={{ ...imageStyle, position: "absolute", inset: 0, opacity: 1 - selected.opacity }} /> : null}
        {shot.parameter_sequence ? <ParameterCallout shot={shot} /> : null}
        {shot.motion === "light_sweep" ? <div style={{position: "absolute", top: "-20%", bottom: "-20%", width: "30%", left: `${interpolate(easeInOut(progress), [0, 1], [-42, 118])}%`, transform: "skewX(-18deg)", background: "linear-gradient(90deg, transparent, rgba(255,255,255,.34), transparent)", mixBlendMode: "screen", pointerEvents: "none"}} /> : null}
      </div>
    </AbsoluteFill>
  );
};

const EditorInteraction: React.FC<{shot: RenderShot; props: TimelineProps}> = ({shot, props}) => {
  const frame = useCurrentFrame();
  const sequence = shot.editor_flow_sequence;
  if (!sequence) throw new Error(`Editor interaction ${shot.shot_id} has no sequence`);
  const content = safeRect(props, "content", {x: 100, y: 186, w: 856, h: 1536});
  const page = assetFor(sequence.page_asset_id, props.assets);
  const pageRatio = page.width / Math.max(1, page.height);
  const stageWidth = content.w;
  const stageHeight = Math.min(content.h * 0.72, stageWidth / pageRatio);
  const stageLeft = content.x;
  const stageTop = content.y + (content.h - stageHeight) / 2;
  const focusLocal = frame - sequence.focus_frame;
  const modalLocal = frame - sequence.modal_frame;
  const focusReveal = easeOut(clamp(focusLocal / sequence.reveal_frames));
  const modalReveal = easeOut(clamp(modalLocal / sequence.reveal_frames));
  const centerX = sequence.focus_x + sequence.focus_w / 2;
  const centerY = sequence.focus_y + sequence.focus_h / 2;
  const lensSize = Math.min(320, Math.max(190, stageWidth * Math.max(sequence.focus_w, sequence.focus_h) * 2.25));
  const lensLeft = centerX * stageWidth - lensSize / 2;
  const lensTop = centerY * stageHeight - lensSize / 2;
  const zoom = sequence.lens_zoom;
  const pagePush = 1 + focusReveal * 0.055;
  return <AbsoluteFill>
    <div style={{
      position: "absolute", left: stageLeft, top: stageTop, width: stageWidth, height: stageHeight,
      overflow: "hidden", borderRadius: 18, opacity: 1 - modalReveal * 0.72,
      transform: `scale(${pagePush})`, transformOrigin: `${centerX * 100}% ${centerY * 100}%`,
      boxShadow: "0 22px 48px rgba(0,0,0,.48)",
    }}>
      <Media assetId={sequence.page_asset_id} assets={props.assets} style={{width: "100%", height: "100%", objectFit: "fill"}} />
      {focusReveal > 0 && modalReveal < 1 ? <div style={{
        position: "absolute", left: lensLeft, top: lensTop, width: lensSize, height: lensSize,
        borderRadius: "50%", overflow: "hidden", opacity: focusReveal * (1 - modalReveal),
        transform: `scale(${0.72 + focusReveal * 0.28})`,
        border: "5px solid rgba(244,249,255,.96)",
        boxShadow: "0 0 0 5px rgba(34,191,255,.5), 0 18px 42px rgba(0,0,0,.7)",
        background: "#090d13",
      }}>
        <Media assetId={sequence.page_asset_id} assets={props.assets} style={{
          position: "absolute", width: stageWidth * zoom, height: stageHeight * zoom,
          left: lensSize / 2 - centerX * stageWidth * zoom,
          top: lensSize / 2 - centerY * stageHeight * zoom,
          objectFit: "fill",
        }} />
      </div> : null}
    </div>
    {modalReveal > 0 ? <div style={{
      position: "absolute", left: content.x, top: content.y + content.h * 0.12,
      width: content.w, height: content.h * 0.76, opacity: modalReveal,
      transform: `translateY(${(1 - modalReveal) * 42}px) scale(${0.94 + modalReveal * 0.06})`,
      transformOrigin: "center", overflow: "hidden", borderRadius: 22,
      boxShadow: "0 28px 70px rgba(0,0,0,.72)",
    }}>
      <Media assetId={sequence.modal_asset_id} assets={props.assets} style={{width: "100%", height: "100%", objectFit: "contain"}} />
    </div> : null}
  </AbsoluteFill>;
};

const PageTurnCard: React.FC<{ assetId: string; shot: RenderShot; props: TimelineProps }> = ({ assetId, shot, props }) => {
  const frame = useCurrentFrame();
  const local = Math.max(0, frame - shot.start_frame);
  const entrance = easeInOut(local / 22);
  const angle = interpolate(entrance, [0, 0.66, 1], [-76, -12, 0]);
  const scale = interpolate(entrance, [0, 0.7, 1], [0.64, 0.94, 1]);
  const x = interpolate(entrance, [0, 1], [-220, 0]);
  const y = interpolate(entrance, [0, 0.45, 1], [360, -20, 0]);
  const opacity = clamp(local / 4);
  return (
    <AbsoluteFill style={{ perspective: 1600 }}>
      <div
        style={{
          position: "absolute",
          left: safeRect(props, "content", {x: 100, y: 186, w: 856, h: 1536}).x - 26,
          top: safeRect(props, "content", {x: 100, y: 186, w: 856, h: 1536}).y + 424,
          width: safeRect(props, "content", {x: 100, y: 186, w: 856, h: 1536}).w + 76,
          height: Math.round(safeRect(props, "content", {x: 100, y: 186, w: 856, h: 1536}).w * 0.562),
          borderRadius: 28,
          overflow: "hidden",
          opacity,
          transformOrigin: "left center",
          transformStyle: "preserve-3d",
          transform: `translate(${x}px, ${y}px) scale(${scale}) rotateY(${angle}deg)`,
          boxShadow: "0 30px 64px rgba(0,0,0,.58), 0 0 30px rgba(77,156,255,.2)",
          background: "#0a0e14",
        }}
      >
        <Img src={assetUrl(assetId, props.assets)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
    </AbsoluteFill>
  );
};

const horizontalStage = (props: TimelineProps) => {
  const content = safeRect(props, "content", {x: 100, y: 186, w: 856, h: 1536});
  const width = content.w;
  const height = Math.min(Math.round(width * 0.5625), Math.round(content.h * 0.62));
  return {content, width, height, left: content.x, top: content.y + (content.h - height) / 2};
};

const CardFlip3D: React.FC<{ assetId: string; shot: RenderShot; props: TimelineProps }> = ({ assetId, shot, props }) => {
  const frame = useCurrentFrame();
  const local = Math.max(0, frame - shot.start_frame);
  const stage = horizontalStage(props);
  const progress = easeInOut(local / 26);
  const angle = interpolate(progress, [0, 0.72, 1], [-82, -10, 0]);
  const scale = interpolate(progress, [0, 1], [0.72, 1]);
  return <AbsoluteFill style={{perspective: 1600}}>
    <div style={{position: "absolute", left: stage.left, top: stage.top, width: stage.width, height: stage.height, borderRadius: 28, overflow: "hidden", transformOrigin: "left center", transform: `rotateY(${angle}deg) scale(${scale})`, opacity: clamp(local / 4), boxShadow: "0 30px 70px rgba(0,0,0,.62), -18px 0 34px rgba(0,0,0,.38)", background: "#0a0e14"}}>
      <Img src={assetUrl(assetId, props.assets)} style={{width: "100%", height: "100%", objectFit: "cover"}} />
      <div style={{position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(0,0,0,.5), transparent 42%)", opacity: 1 - progress}} />
    </div>
  </AbsoluteFill>;
};

const PaperCurlFlip: React.FC<{ assetId: string; shot: RenderShot; props: TimelineProps }> = ({ assetId, shot, props }) => {
  const frame = useCurrentFrame();
  const local = Math.max(0, frame - shot.start_frame);
  const stage = horizontalStage(props);
  const available = Math.max(1, shot.end_frame - shot.start_frame);
  const animationFrames = Math.max(1, Math.min(34, available));
  const progress = easeInOut(clamp(local / Math.max(1, animationFrames - 1)));
  const columns = 18;
  const source = assetUrl(assetId, props.assets);
  return <AbsoluteFill style={{perspective: 1800}}>
    <div style={{position: "absolute", left: stage.left, top: stage.top, width: stage.width, height: stage.height, borderRadius: 28, overflow: "hidden", opacity: clamp(local / 4), boxShadow: "0 30px 70px rgba(0,0,0,.6)", background: "#0a0e14"}}>
      {Array.from({length: columns}, (_, index) => {
        const x = index / (columns - 1);
        const curl = Math.sin(x * Math.PI) * (1 - progress);
        const angle = -68 * (1 - progress) * (1 - x * 0.42);
        const width = stage.width / columns + 1;
        return <div key={index} style={{position: "absolute", left: index * stage.width / columns, top: 0, width, height: stage.height, transformOrigin: "left center", transform: `translateX(${-curl * 74}px) rotateY(${angle}deg)`, backgroundImage: `url(${source})`, backgroundSize: `${stage.width}px ${stage.height}px`, backgroundPosition: `${-index * stage.width / columns}px 0`, boxShadow: curl > .01 ? "7px 0 14px rgba(0,0,0,.26)" : "none"}} />;
      })}
      <div style={{position: "absolute", inset: 0, background: "linear-gradient(110deg, rgba(0,0,0,.46), transparent 40%)", opacity: (1 - progress) * .8, pointerEvents: "none"}} />
    </div>
  </AbsoluteFill>;
};

const galleryItems = (shot: RenderShot) => {
  const items = shot.gallery_items ?? [];
  if (items.length) return [...items].sort((a, b) => (a.onset_frame ?? a.hit_frame) - (b.onset_frame ?? b.hit_frame));
  const ids = Object.values(shot.asset_bindings);
  const duration = Math.max(1, shot.end_frame - shot.start_frame);
  return ids.map((asset_id, index) => {
    const onset = shot.start_frame + Math.floor(index * duration / ids.length);
    return {asset_id, anchor_id: `legacy_${index}`, hit_frame: onset, onset_frame: onset};
  });
};

const galleryState = (shot: RenderShot, frame: number) => {
  const items = galleryItems(shot);
  const transitionFramesFor = (index: number) => {
    const onset = items[index].onset_frame ?? items[index].hit_frame;
    const nextOnset = index + 1 < items.length
      ? (items[index + 1].onset_frame ?? items[index + 1].hit_frame)
      : shot.end_frame;
    const available = Math.max(1, nextOnset - onset);
    return Math.max(1, Math.min(8, Math.floor(available * 0.45)));
  };
  const active = Math.max(0, items.reduce((selected, item, index) => {
    const onset = item.onset_frame ?? item.hit_frame;
    return index > 0 && onset + transitionFramesFor(index) <= frame ? index : selected;
  }, 0));
  const next = items[active + 1];
  // The next image contributes its first visible pixels on the spoken onset,
  // never during the previous phrase.
  const nextOnset = next ? (next.onset_frame ?? next.hit_frame) : 0;
  const transitionFrames = next ? transitionFramesFor(active + 1) : 1;
  const transition = next ? easeInOut(clamp((frame - nextOnset + 1) / transitionFrames)) : 0;
  return {items, active, transition};
};

const galleryStage = (assetId: string, props: TimelineProps) => {
  const content = safeRect(props, "content", {x: 92, y: 188, w: 860, h: 1390});
  const asset = assetFor(assetId, props.assets);
  const ratio = asset.width / asset.height;
  if (ratio < 0.82) {
    const height = Math.min(content.h, 1360);
    const width = Math.min(content.w * 0.86, height * ratio);
    return {left: content.x + (content.w - width) / 2, top: content.y + (content.h - height) / 2, width, height};
  }
  const width = content.w;
  const height = Math.min(content.h, width / ratio);
  return {left: content.x, top: content.y + (content.h - height) / 2, width, height};
};

const SlideGallery: React.FC<{ shot: RenderShot; props: TimelineProps }> = ({ shot, props }) => {
  const frame = useCurrentFrame();
  const {items, active, transition} = galleryState(shot, frame);
  const content = safeRect(props, "content", {x: 92, y: 188, w: 860, h: 1390});
  const travel = content.w + 64;
  return <AbsoluteFill style={{overflow: "hidden"}}>
    {items.map((item, itemIndex) => {
      const delta = itemIndex - active;
      if (Math.abs(delta) > 1) return null;
      const stage = galleryStage(item.asset_id, props);
      const x = delta === 0 ? -transition * travel : travel - transition * travel;
      return <div key={`${item.asset_id}_${item.anchor_id}`} style={{position: "absolute", left: stage.left, top: stage.top, width: stage.width, height: stage.height, borderRadius: 28, overflow: "hidden", transform: `translateX(${x}px)`, boxShadow: "0 24px 54px rgba(0,0,0,.58)", background: "transparent"}}>
        <Img src={assetUrl(item.asset_id, props.assets)} style={{width: "100%", height: "100%", objectFit: "contain"}} />
      </div>;
    })}
  </AbsoluteFill>;
};

const CardStack: React.FC<{ shot: RenderShot; props: TimelineProps }> = ({ shot, props }) => {
  const frame = useCurrentFrame();
  const {items, active, transition: peel} = galleryState(shot, frame);
  const content = safeRect(props, "content", {x: 92, y: 188, w: 860, h: 1390});
  const travel = content.w + 90;
  return <AbsoluteFill style={{perspective: 1600}}>
    {items.slice(Math.max(0, active - 2), active + 1).map((item, visibleIndex, visible) => {
      const cardIndex = active - (visible.length - 1 - visibleIndex);
      const depth = active - cardIndex;
      const topCard = depth === 0;
      const stage = galleryStage(item.asset_id, props);
      const x = topCard ? peel * travel : -depth * 15;
      const rotate = topCard ? peel * 16 : -depth * 2.5;
      return <div key={`${item.asset_id}_${item.anchor_id}`} style={{position: "absolute", left: stage.left, top: stage.top + depth * 12, width: stage.width, height: stage.height, borderRadius: 28, overflow: "hidden", transformOrigin: "right center", transform: `translateX(${x}px) rotate(${rotate}deg) scale(${1 - depth * .035})`, zIndex: 10 - depth, boxShadow: "0 25px 56px rgba(0,0,0,.62)", background: "transparent"}}>
        <Img src={assetUrl(item.asset_id, props.assets)} style={{width: "100%", height: "100%", objectFit: "contain"}} />
      </div>;
    })}
  </AbsoluteFill>;
};

const FullBleedToSafeCard: React.FC<{ assetId: string; shot: RenderShot; props: TimelineProps }> = ({ assetId, shot, props }) => {
  const frame = useCurrentFrame();
  const local = Math.max(0, frame - shot.start_frame);
  const available = Math.max(1, shot.end_frame - shot.start_frame);
  const animationFrames = Math.max(1, Math.min(30, available));
  const settle = easeInOut(clamp(local / Math.max(1, animationFrames - 1)));
  const asset = assetFor(assetId, props.assets);
  const accent = asset.accent_color ?? "#f5c518";
  const content = safeRect(props, "content", {x: 100, y: 186, w: 856, h: 1536});
  const safeWidth = content.w;
  const safeHeight = Math.min(content.h, safeWidth * asset.height / asset.width);
  const safeTop = content.y + (content.h - safeHeight) / 2;
  const left = interpolate(settle, [0, 1], [0, content.x]);
  const top = interpolate(settle, [0, 1], [0, safeTop]);
  const width = interpolate(settle, [0, 1], [props.width, safeWidth]);
  const height = interpolate(settle, [0, 1], [props.height, safeHeight]);
  const radius = interpolate(settle, [0, 1], [0, 28]);
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left,
          top,
          width,
          height,
          overflow: "hidden",
          borderRadius: radius,
          backgroundColor: "#080b0f",
          boxShadow: `0 0 ${interpolate(settle, [0, 1], [0, 34])}px ${accent}, 0 20px 44px rgba(0,0,0,.54)`,
        }}
      >
        <Img src={assetUrl(assetId, props.assets)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        <div style={{ position: "absolute", inset: 0, backgroundColor: accent, opacity: 0.72 * Math.pow(1 - settle, 1.7), mixBlendMode: "color" }} />
        <div style={{ position: "absolute", inset: 0, border: `${interpolate(settle, [0, 1], [0, 5])}px solid ${accent}`, borderRadius: radius, pointerEvents: "none" }} />
      </div>
    </AbsoluteFill>
  );
};

const GridRevealCard: React.FC<{ assetIds: string[]; shot: RenderShot; props: TimelineProps }> = ({ assetIds, shot, props }) => {
  const frame = useCurrentFrame();
  const local = Math.max(0, frame - shot.start_frame);
  const content = safeRect(props, "content", {x: 100, y: 186, w: 856, h: 1536});
  const width = content.w;
  const height = Math.min(content.h, Math.round(content.w * 1.12));
  const top = content.y + (content.h - height) / 2;
  const cells = Array.from({length: 12}, (_, index) => index);
  if (assetIds.length > 1) {
    const columns = 2;
    const rows = Math.ceil(assetIds.length / columns);
    const gap = 16;
    const cardWidth = (width - gap * (columns - 1)) / columns;
    const cardHeight = (height - gap * (rows - 1)) / rows;
    return <AbsoluteFill>{assetIds.map((assetId, index) => {
      const row = Math.floor(index / columns);
      const column = index % columns;
      const reveal = easeOut(clamp((local - index * 5) / 14));
      return <div key={assetId} style={{position: "absolute", left: content.x + column * (cardWidth + gap), top: top + row * (cardHeight + gap), width: cardWidth, height: cardHeight, borderRadius: 20, overflow: "hidden", opacity: reveal, transform: `scale(${.78 + reveal * .22}) translateY(${(1 - reveal) * 24}px)`, boxShadow: "0 18px 36px rgba(0,0,0,.5)", background: "#10151c"}}>
        <Img src={assetUrl(assetId, props.assets)} style={{width: "100%", height: "100%", objectFit: "cover"}} />
      </div>;
    })}</AbsoluteFill>;
  }
  const assetId = assetIds[0];
  return <AbsoluteFill>
    <div style={{position: "absolute", left: content.x, top, width, height, overflow: "hidden", borderRadius: 28, boxShadow: "0 20px 44px rgba(0,0,0,.5)", background: "#10151c"}}>
      <Img src={assetUrl(assetId, props.assets)} style={{width: "100%", height: "100%", objectFit: "contain"}} />
      {cells.map((index) => {
        const row = Math.floor(index / 3);
        const column = index % 3;
        const reveal = clamp((local - index * 2) / 10);
        return <div key={index} style={{position: "absolute", left: `${column * 33.333}%`, top: `${row * 25}%`, width: "33.34%", height: "25.1%", background: "#070a0e", opacity: 1 - easeOut(reveal), border: "1px solid rgba(110,130,150,.38)"}} />;
      })}
    </div>
  </AbsoluteFill>;
};

const ReferenceComparison: React.FC<{ shot: RenderShot; props: TimelineProps }> = ({ shot, props }) => {
  const frame = useCurrentFrame();
  const local = frame - shot.start_frame;
  const resultOpacity = clamp((local - 10) / 10);
  const labels = shot.scene_kind === "result_to_flat_plan"
    ? ["生成效果", "导出平面图"]
    : shot.scene_kind === "editor_before_after"
      ? ["编辑前", "编辑后"]
      : ["实景参考", "生成效果"];
  const referenceId = shot.scene_kind === "reference_to_result" ? shot.asset_bindings.output : shot.asset_bindings.input;
  const referenceAsset = referenceId ? assetFor(referenceId, props.assets) : null;
  const ratio = referenceAsset ? referenceAsset.width / referenceAsset.height : 16 / 9;
  const cardWidth = 816;
  const cardHeight = Math.min(540, cardWidth / Math.max(0.05, ratio));
  const cards = [
    [labels[0], shot.asset_bindings.input, 360, cardHeight, 0.92],
    [labels[1], shot.asset_bindings.output, 1020, cardHeight, 1],
  ] as const;
  return <AbsoluteFill>{cards.map(([label, id, top, height, opacity]) => id ? (
    <div key={label} style={{ position: "absolute", left: 132, top, width: 816, height, borderRadius: 24, overflow: "hidden", opacity: id === shot.asset_bindings.output ? resultOpacity : opacity, boxShadow: "8px 18px 28px rgba(0,0,0,.48)" }}>
      <Img src={assetUrl(id, props.assets)} style={{ width: "100%", height: "100%", objectFit: "contain", background: "transparent" }} />
      <div style={{ position: "absolute", top: 18, left: 18, padding: "10px 18px", borderRadius: 18, background: "rgba(7,10,14,.82)", color: "#f5f7fb", fontSize: 28, fontWeight: 700 }}>{label}</div>
    </div>
  ) : null)}</AbsoluteFill>;
};

const Subtitle: React.FC<{ cue: SubtitleCue; props: TimelineProps }> = ({ cue, props }) => {
  const frame = useCurrentFrame();
  const local = frame - cue.start_frame;
  const opacity = clamp(local / 5);
  const safe = safeRect(props, cue.slot === "subtitle_top" ? "subtitle_top" : "subtitle_lower", cue.slot === "subtitle_top" ? {x: 90, y: 138, w: 820, h: 116} : {x: 90, y: 1320, w: 760, h: 116});
  const parts = cue.emphasize && cue.text.includes(cue.emphasize) ? cue.text.split(cue.emphasize) : null;
  const units = Array.from(cue.text).reduce((total, char) => total + (char.charCodeAt(0) > 0x2e80 ? 1 : .5), 0);
  const fontSize = Math.max(48, Math.min(64, Math.floor(safe.w / Math.max(1, units))));
  const galleryStyle = cue.style === "gallery_yellow";
  return <div style={{ position: "absolute", top: safe.y, left: safe.x, width: safe.w, minHeight: safe.h, display: "flex", alignItems: "center", justifyContent: "center", color: galleryStyle ? "#ffd400" : "#fafafa", fontFamily: "Noto Sans CJK SC, Microsoft YaHei, sans-serif", fontWeight: 800, fontSize, lineHeight: 1.14, whiteSpace: "nowrap", opacity, textShadow: "0 4px 0 #080a0e, 2px 0 0 #080a0e, -2px 0 0 #080a0e" }}>
    {parts ? <>{parts[0]}<span style={{ color: "#ffd44a" }}>{cue.emphasize}</span>{parts[1]}</> : cue.text}
  </div>;
};

const BaseLayer: React.FC<{ shot: RenderShot; props: TimelineProps; opacity?: number; translateX?: number }> = ({ shot, props, opacity = 1, translateX = 0 }) => (
  <div style={{position: "absolute", inset: 0, opacity, transform: `translateX(${translateX}px)`}}>
    {shot.template === "reference_to_result" || shot.motion === "before_after"
      ? <ReferenceComparison shot={shot} props={props} />
      : <MotionImage shot={shot} props={props} />}
  </div>
);

export const VerticalDemo: React.FC<TimelineProps> = (props) => {
  const frame = useCurrentFrame();
  const baseShots = props.shots.filter((shot) => shot.track === "base").sort((left, right) => left.start_frame - right.start_frame);
  const base = baseShots.filter((shot) => shot.start_frame <= frame && frame < shot.end_frame).at(-1);
  const baseIndex = base ? baseShots.findIndex((shot) => shot.shot_id === base.shot_id) : -1;
  const previous = baseIndex > 0 ? baseShots[baseIndex - 1] : null;
  const transition = base?.transition_in;
  const transitionFrames = transition?.kind === "cut" ? 0 : Math.max(0, transition?.duration_frames ?? 0);
  const transitionProgress = base && transitionFrames > 0 ? clamp((frame - base.start_frame) / transitionFrames) : 1;
  const transitionActive = Boolean(base && previous && transitionFrames > 0 && frame < base.start_frame + transitionFrames);
  const overlays = props.shots.filter((shot) => shot.track === "overlay" && shot.start_frame <= frame && frame < shot.end_frame).sort((a, b) => (a.overlay_layout?.z_index ?? 10) - (b.overlay_layout?.z_index ?? 10));
  const subtitle = props.subtitles.find((cue) => cue.start_frame <= frame && frame < cue.end_frame);
  const direction = transition?.kind === "slide_left" ? -1 : 1;
  return <AbsoluteFill>
    <Grid />
    {transitionActive && previous && transition?.kind === "crossfade" ? <BaseLayer shot={previous} props={props} opacity={1 - transitionProgress} /> : null}
    {transitionActive && previous && (transition?.kind === "slide_left" || transition?.kind === "slide_right") ? <BaseLayer shot={previous} props={props} translateX={direction * props.width * transitionProgress} /> : null}
    {base ? <BaseLayer shot={base} props={props} opacity={transitionActive && transition?.kind === "crossfade" ? transitionProgress : 1} translateX={transitionActive && (transition?.kind === "slide_left" || transition?.kind === "slide_right") ? -direction * props.width * (1 - transitionProgress) : 0} /> : null}
    {overlays.map((shot) => <MotionImage key={shot.shot_id} shot={shot} props={props} />)}
    {subtitle ? <Subtitle cue={subtitle} props={props} /> : null}
  </AbsoluteFill>;
};
