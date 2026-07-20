import { Composition } from "remotion";
import { V4Timeline } from "./v4/Timeline";
import type { V4TimelineProps } from "./v4/types";

const v4Defaults: V4TimelineProps = {
  composition_id: "V4Timeline",
  schema_version: 1,
  case_id: "case",
  run_id: "run",
  width: 1080,
  height: 1920,
  fps: 30,
  frame_count: 30,
  platform_profile_id: "douyin_portrait_v1",
  platform_profile: {
    profile_id: "douyin_portrait_v1",
    canvas: {x: 0, y: 0, w: 1080, h: 1920},
    subtitle_top: {x: 90, y: 138, w: 820, h: 116},
    subtitle_lower: {x: 90, y: 1320, w: 760, h: 116},
    subtitle_font_px: 56,
  },
  render_assets: [],
  visual_tracks: [],
  effect_instances: [],
  effect_props: [],
  subtitle_track: [],
  audio_tracks: [],
};

export const Root = () => (
  <Composition
    id="V4Timeline"
    component={V4Timeline}
    defaultProps={v4Defaults}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={30}
    calculateMetadata={({ props }) => ({
      width: props.width,
      height: props.height,
      fps: props.fps,
      durationInFrames: props.frame_count,
    })}
  />
);
