import type { FtshareOperation } from '@panwatch/api'

export function normalizeEndpointTerm(value: string) {
  return value.normalize('NFKC').toLowerCase().replace(/[\s_:/.-]+/g, '')
}

export function endpointSearchTokens(query: string) {
  return query.normalize('NFKC').trim().split(/\s+/).map(normalizeEndpointTerm).filter(Boolean)
}

export function matchesEndpointSearch(index: string[], tokens: string[]) {
  return tokens.every(token => index.some(value => value.includes(token)))
}

export function ftshareSearchFields(operation: FtshareOperation) {
  return [
    operation.id, operation.summary, operation.group, operation.subgroup ?? '',
    ...operation.variants.flatMap(variant => [variant.path, ...variant.parameters.map(param => param.name)]),
  ]
}
