import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export type AgentTestScene = {
  scene_id: string;
  cue_id: string;
  text: string;
  start_frame: number;
  end_frame: number;
  kind: "website_operation" | "result_detail" | "result_gallery" | "before_after" | "title_card";
  motion: string;
  sources: string[];
};

export type AgentTestSubtitle = {
  cue_id: string;
  text: string;
  start_frame: number;
  end_frame: number;
};

export type AgentTestProps = {
  width: number;
  height: number;
  fps: number;
  frame_count: number;
  voice_path: string;
  title: string;
  scenes: AgentTestScene[];
  subtitles: AgentTestSubtitle[];
};

const background = "linear-gradient(160deg, #0b1020 0%, #111a35 55%, #090d18 100%)";

const BrowserScene: React.FC<{ scene: AgentTestScene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 18, stiffness: 140 } });
  const scale = interpolate(enter, [0, 1], [0.94, 1]);
  const source = scene.sources[0];
  return (
    <AbsoluteFill style={{ background, alignItems: "center", justifyContent: "center" }}>
      <div
        style={{
          width: "92%",
          height: "72%",
          borderRadius: 32,
          overflow: "hidden",
          border: "3px solid rgba(255,255,255,.28)",
          boxShadow: "0 34px 100px rgba(0,0,0,.55)",
          transform: `scale(${scale})`,
          background: "#fff",
        }}
      >
        {source ? (
          <OffthreadVideo
            src={staticFile(source)}
            muted
            style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "center" }}
          />
        ) : null}
      </div>
      <div
        style={{
          position: "absolute",
          top: 170,
          left: 90,
          padding: "18px 28px",
          borderRadius: 999,
          color: "white",
          background: "rgba(7,12,26,.78)",
          border: "1px solid rgba(255,255,255,.2)",
          fontSize: 34,
          fontWeight: 800,
          letterSpacing: 1,
        }}
      >
        Agent 正在操作真实网站
      </div>
    </AbsoluteFill>
  );
};

const SingleImageScene: React.FC<{ scene: AgentTestScene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const duration = Math.max(1, scene.end_frame - scene.start_frame);
  const progress = interpolate(frame, [0, duration], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const scale = 1.02 + progress * 0.08;
  const source = scene.sources[0];
  return (
    <AbsoluteFill style={{ background, alignItems: "center", justifyContent: "center" }}>
      <div
        style={{
          width: "88%",
          height: "70%",
          overflow: "hidden",
          borderRadius: 38,
          boxShadow: "0 40px 110px rgba(0,0,0,.58)",
          border: "2px solid rgba(255,255,255,.22)",
          background: "rgba(255,255,255,.06)",
        }}
      >
        {source ? (
          <Img
            src={staticFile(source)}
            style={{ width: "100%", height: "100%", objectFit: "contain", transform: `scale(${scale})` }}
          />
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

const GalleryScene: React.FC<{ scene: AgentTestScene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const sources = scene.sources.slice(0, 4);
  return (
    <AbsoluteFill style={{ background, padding: "210px 70px 360px", boxSizing: "border-box" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 28, width: "100%", height: "100%" }}>
        {sources.map((source, index) => {
          const enter = spring({ frame: frame - index * 4, fps, config: { damping: 18, stiffness: 150 } });
          return (
            <div
              key={source}
              style={{
                overflow: "hidden",
                borderRadius: 28,
                background: "rgba(255,255,255,.06)",
                border: "2px solid rgba(255,255,255,.2)",
                boxShadow: "0 24px 65px rgba(0,0,0,.42)",
                transform: `translateY(${interpolate(enter, [0, 1], [90, 0])}px) scale(${interpolate(enter, [0, 1], [0.9, 1])})`,
                opacity: enter,
              }}
            >
              <Img src={staticFile(source)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const BeforeAfterScene: React.FC<{ scene: AgentTestScene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const duration = Math.max(1, scene.end_frame - scene.start_frame);
  const divider = interpolate(frame, [0, duration], [36, 64], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const [before, after] = scene.sources;
  return (
    <AbsoluteFill style={{ background, alignItems: "center", justifyContent: "center" }}>
      <div style={{ position: "relative", width: "88%", height: "68%", overflow: "hidden", borderRadius: 36 }}>
        {after ? <Img src={staticFile(after)} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : null}
        {before ? (
          <div style={{ position: "absolute", inset: 0, width: `${divider}%`, overflow: "hidden", borderRight: "5px solid white" }}>
            <Img src={staticFile(before)} style={{ width: `${100 / (divider / 100)}%`, height: "100%", objectFit: "cover" }} />
          </div>
        ) : null}
        <div style={{ position: "absolute", left: 24, top: 24, color: "white", fontSize: 34, fontWeight: 900 }}>改前</div>
        <div style={{ position: "absolute", right: 24, top: 24, color: "white", fontSize: 34, fontWeight: 900 }}>改后</div>
      </div>
    </AbsoluteFill>
  );
};

const TitleScene: React.FC<{ scene: AgentTestScene; title: string }> = ({ scene, title }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 16, stiffness: 135 } });
  return (
    <AbsoluteFill style={{ background, alignItems: "center", justifyContent: "center", padding: 100, boxSizing: "border-box" }}>
      <div style={{ color: "#7fd9ff", fontSize: 32, fontWeight: 800, marginBottom: 30, opacity: enter }}>{title}</div>
      <div
        style={{
          color: "white",
          fontSize: 72,
          lineHeight: 1.22,
          fontWeight: 950,
          textAlign: "center",
          transform: `scale(${interpolate(enter, [0, 1], [0.82, 1])})`,
          opacity: enter,
          textShadow: "0 16px 48px rgba(0,0,0,.55)",
        }}
      >
        {scene.text}
      </div>
    </AbsoluteFill>
  );
};

const SceneView: React.FC<{ scene: AgentTestScene; title: string }> = ({ scene, title }) => {
  if (scene.kind === "website_operation") return <BrowserScene scene={scene} />;
  if (scene.kind === "result_gallery") return <GalleryScene scene={scene} />;
  if (scene.kind === "before_after") return <BeforeAfterScene scene={scene} />;
  if (scene.kind === "result_detail") return <SingleImageScene scene={scene} />;
  return <TitleScene scene={scene} title={title} />;
};

const SubtitleLayer: React.FC<{ subtitles: AgentTestSubtitle[] }> = ({ subtitles }) => (
  <AbsoluteFill style={{ pointerEvents: "none" }}>
    {subtitles.map((cue) => (
      <Sequence key={cue.cue_id} from={cue.start_frame} durationInFrames={Math.max(1, cue.end_frame - cue.start_frame)}>
        <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 235, boxSizing: "border-box" }}>
          <div
            style={{
              maxWidth: 900,
              padding: "16px 26px",
              borderRadius: 20,
              color: "white",
              background: "rgba(0,0,0,.72)",
              fontSize: 47,
              lineHeight: 1.35,
              fontWeight: 900,
              textAlign: "center",
              textShadow: "0 3px 8px rgba(0,0,0,.8)",
              boxShadow: "0 10px 30px rgba(0,0,0,.3)",
            }}
          >
            {cue.text}
          </div>
        </AbsoluteFill>
      </Sequence>
    ))}
  </AbsoluteFill>
);

export const AgentTest: React.FC<AgentTestProps> = (props) => (
  <AbsoluteFill style={{ background: "#090d18", fontFamily: '"Noto Sans CJK SC", "Microsoft YaHei", sans-serif' }}>
    <Audio src={staticFile(props.voice_path)} />
    {props.scenes.map((scene) => (
      <Sequence key={scene.scene_id} from={scene.start_frame} durationInFrames={Math.max(1, scene.end_frame - scene.start_frame)}>
        <SceneView scene={scene} title={props.title} />
      </Sequence>
    ))}
    <SubtitleLayer subtitles={props.subtitles} />
  </AbsoluteFill>
);
