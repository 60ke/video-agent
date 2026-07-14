import { Composition } from "remotion";
import { VerticalDemo } from "./VerticalDemo";
import type { TimelineProps } from "./types";

const defaults: TimelineProps = {
  width: 1080,
  height: 1920,
  fps: 30,
  frame_count: 30,
  assets: [],
  shots: [],
  subtitles: [],
};

export const Root = () => (
  <Composition
    id="VerticalDemo"
    component={VerticalDemo}
    defaultProps={defaults}
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
