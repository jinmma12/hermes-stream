using Hermes.Api.Contracts;

namespace Hermes.Api.Services;

public interface IHermesReadStore
{
    IReadOnlyList<DefinitionSummaryDto> ListDefinitions(string kind);
    DefinitionSummaryDto? GetDefinition(string kind, Guid definitionId);
    IReadOnlyList<DefinitionVersionDto> ListDefinitionVersions(string kind, Guid definitionId);
    IReadOnlyList<PipelineSummaryDto> ListPipelines();
    PipelineSummaryDto? GetPipeline(Guid pipelineId);
    IReadOnlyList<PipelineStageDto> ListPipelineStages(Guid pipelineId);
    PaginatedResponseDto<JobSummaryDto> ListJobs(int page, int pageSize);
    JobSummaryDto? GetJob(Guid jobId);
    MonitorStatsDto GetMonitorStats();
    IReadOnlyList<PipelineActivationDto> ListMonitorActivations();
    IReadOnlyList<JobSummaryDto> ListRecentJobs(int limit);
}
