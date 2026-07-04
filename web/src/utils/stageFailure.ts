import type { StageInfo } from '../types';

export interface FailedStageDetail {
  stageName: string;
  errorMessage: string | null;
}

function normalizeErrorMessage(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

export function getFailedStageDetail(
  stages: StageInfo[],
  currentStage?: string | null,
): FailedStageDetail | null {
  const currentStageName = normalizeErrorMessage(currentStage);
  const failedStage =
    stages.find((stage) => stage.status === 'failed' && normalizeErrorMessage(stage.error_message)) ||
    stages.find((stage) => stage.status === 'failed') ||
    (currentStageName ? stages.find((stage) => stage.name === currentStageName) : undefined);

  if (!failedStage && !currentStageName) return null;

  return {
    stageName: failedStage?.name || currentStageName!,
    errorMessage: normalizeErrorMessage(failedStage?.error_message),
  };
}
