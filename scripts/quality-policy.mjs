export const resolveQualityPolicy = (job, config, sourceProfile = null) => {
  const format = job?.format ?? "short";
  if (format !== "short" && format !== "long") {
    throw new Error(`Unsupported Telic format: ${format}`);
  }

  const quality = format === "long" ? config?.longForm?.quality : config?.quality;
  if (!quality || typeof quality !== "object") {
    throw new Error(`The private config has no ${format} quality policy.`);
  }

  const expectedWidth = format === "long" ? 1920 : 1080;
  const expectedHeight = format === "long" ? 1080 : 1920;
  const channelDurationPolicy = format === "long" ? sourceProfile?.long : sourceProfile?.short;
  const fallbackMinimum = format === "long"
    ? Number(config?.longForm?.minimumDurationSeconds ?? 240)
    : 10;
  const fallbackMaximum = Number(quality.maximumDurationSeconds);
  const minimumDurationSeconds = Number(channelDurationPolicy?.minimumDurationSeconds ?? fallbackMinimum);
  const maximumDurationSeconds = Number(channelDurationPolicy?.maximumDurationSeconds ?? fallbackMaximum);
  const maximumFrames = Number(quality.maximumFrames) || (format === "long" ? 48 : 20);

  if (!Number.isFinite(minimumDurationSeconds) || minimumDurationSeconds <= 0) {
    throw new Error(`${format} minimum duration policy is invalid.`);
  }
  if (!Number.isFinite(maximumDurationSeconds) || maximumDurationSeconds <= minimumDurationSeconds) {
    throw new Error(`${format} maximum duration policy is invalid.`);
  }

  return {
    format,
    quality,
    expectedWidth,
    expectedHeight,
    minimumDurationSeconds,
    maximumDurationSeconds,
    maximumFrames,
  };
};
