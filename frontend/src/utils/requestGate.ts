export type RequestGateToken = Readonly<{ generation: number }>

export class AbortableRequestGate {
  private generation = 0
  private controller: AbortController | null = null

  invalidate() {
    this.controller?.abort()
    this.controller = null
    this.generation += 1
  }

  start() {
    this.invalidate()
    const controller = new AbortController()
    const token: RequestGateToken = { generation: this.generation }
    this.controller = controller
    return {
      signal: controller.signal,
      token,
      isCurrent: () => this.controller === controller && this.generation === token.generation,
    }
  }
}
