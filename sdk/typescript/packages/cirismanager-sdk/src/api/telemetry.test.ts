import { AxiosInstance } from 'axios';
import { TelemetryAPI } from './telemetry';

describe('TelemetryAPI', () => {
  let api: TelemetryAPI;
  let mockAxios: jest.Mocked<AxiosInstance>;

  beforeEach(() => {
    mockAxios = {
      get: jest.fn(),
      post: jest.fn(),
    } as any;

    api = new TelemetryAPI(mockAxios);
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
  });

  describe('health', () => {
    it('should fetch telemetry health', async () => {
      const mockHealth = {
        status: 'healthy',
        collectors_total: 5,
        collectors_healthy: 5,
        last_collection: '2024-01-01T00:00:00Z'
      };

      mockAxios.get.mockResolvedValue({ data: mockHealth });

      const result = await api.health();

      expect(mockAxios.get).toHaveBeenCalledWith('/telemetry/health');
      expect(result).toEqual(mockHealth);
    });
  });

  describe('getStatus', () => {
    it('should fetch current telemetry status', async () => {
      const mockStatus = {
        timestamp: '2024-01-01T00:00:00Z',
        agents_total: 10,
        agents_running: 8,
        agents_stopped: 2,
        agents_in_crash_loop: 0,
        cpu_percent: 45.5,
        memory_used_gb: 3.2,
        memory_total_gb: 16.0,
        disk_used_gb: 120.0,
        disk_total_gb: 500.0
      };

      mockAxios.get.mockResolvedValue({ data: mockStatus });

      const result = await api.getStatus();

      expect(mockAxios.get).toHaveBeenCalledWith('/telemetry/status');
      expect(result).toEqual(mockStatus);
    });
  });

  describe('getHistory', () => {
    it('should fetch telemetry history with defaults', async () => {
      const mockHistory = {
        hours: 24,
        interval: '5m',
        data: [
          { timestamp: '2024-01-01T00:00:00Z', cpu_percent: 40 },
          { timestamp: '2024-01-01T00:05:00Z', cpu_percent: 45 }
        ]
      };

      mockAxios.get.mockResolvedValue({ data: mockHistory });

      const result = await api.getHistory();

      expect(mockAxios.get).toHaveBeenCalledWith('/telemetry/history', {
        params: { hours: 24, interval: '5m' }
      });
      expect(result).toEqual(mockHistory);
    });

    it('should fetch telemetry history with custom options', async () => {
      const mockHistory = {
        hours: 48,
        interval: '1h',
        data: []
      };

      mockAxios.get.mockResolvedValue({ data: mockHistory });

      const result = await api.getHistory({ hours: 48, interval: '1h' });

      expect(mockAxios.get).toHaveBeenCalledWith('/telemetry/history', {
        params: { hours: 48, interval: '1h' }
      });
      expect(result).toEqual(mockHistory);
    });
  });

  describe('getPublicStatus', () => {
    it('should fetch public status', async () => {
      const mockPublicStatus = {
        status: 'operational',
        agents_active: 8,
        uptime_percent: 99.95,
        last_updated: '2024-01-01T00:00:00Z'
      };

      mockAxios.get.mockResolvedValue({ data: mockPublicStatus });

      const result = await api.getPublicStatus();

      expect(mockAxios.get).toHaveBeenCalledWith('/telemetry/public/status');
      expect(result).toEqual(mockPublicStatus);
    });
  });

  describe('getPublicHistory', () => {
    it('should fetch public history', async () => {
      const mockPublicHistory = [
        { timestamp: '2024-01-01T00:00:00Z', status: 'operational' },
        { timestamp: '2024-01-01T01:00:00Z', status: 'operational' }
      ];

      mockAxios.get.mockResolvedValue({ data: mockPublicHistory });

      const result = await api.getPublicHistory(48);

      expect(mockAxios.get).toHaveBeenCalledWith('/telemetry/public/history', {
        params: { hours: 48 }
      });
      expect(result).toEqual(mockPublicHistory);
    });

    it('should use default hours', async () => {
      mockAxios.get.mockResolvedValue({ data: [] });

      await api.getPublicHistory();

      expect(mockAxios.get).toHaveBeenCalledWith('/telemetry/public/history', {
        params: { hours: 24 }
      });
    });
  });

  describe('getAgentMetrics', () => {
    it('should fetch agent-specific metrics', async () => {
      const mockMetrics = {
        agent_name: 'test-agent',
        cpu_usage: [10, 15, 20],
        memory_usage: [512, 550, 600],
        request_count: 150
      };

      mockAxios.get.mockResolvedValue({ data: mockMetrics });

      const result = await api.getAgentMetrics('test-agent', 12);

      expect(mockAxios.get).toHaveBeenCalledWith('/telemetry/agent/test-agent', {
        params: { hours: 12 }
      });
      expect(result).toEqual(mockMetrics);
    });

    it('should use default hours for agent metrics', async () => {
      mockAxios.get.mockResolvedValue({ data: {} });

      await api.getAgentMetrics('test-agent');

      expect(mockAxios.get).toHaveBeenCalledWith('/telemetry/agent/test-agent', {
        params: { hours: 24 }
      });
    });
  });

  describe('getContainerMetrics', () => {
    it('should fetch container-specific metrics', async () => {
      const mockMetrics = {
        container_name: 'ciris-agent-test',
        cpu_percent: 25.5,
        memory_used_mb: 768,
        network_rx_mb: 100,
        network_tx_mb: 50
      };

      mockAxios.get.mockResolvedValue({ data: mockMetrics });

      const result = await api.getContainerMetrics('ciris-agent-test', 6);

      expect(mockAxios.get).toHaveBeenCalledWith('/telemetry/container/ciris-agent-test', {
        params: { hours: 6 }
      });
      expect(result).toEqual(mockMetrics);
    });

    it('should use default hours for container metrics', async () => {
      mockAxios.get.mockResolvedValue({ data: {} });

      await api.getContainerMetrics('ciris-agent-test');

      expect(mockAxios.get).toHaveBeenCalledWith('/telemetry/container/ciris-agent-test', {
        params: { hours: 24 }
      });
    });
  });

  describe('collect', () => {
    it('should trigger manual telemetry collection', async () => {
      const mockResponse = {
        status: 'success',
        message: 'Telemetry collection triggered'
      };

      mockAxios.post.mockResolvedValue({ data: mockResponse });

      const result = await api.collect();

      expect(mockAxios.post).toHaveBeenCalledWith('/telemetry/collect');
      expect(result).toEqual(mockResponse);
    });
  });

  describe('streamMetrics', () => {
    it('should start streaming telemetry updates', () => {
      const onUpdate = jest.fn();
      mockAxios.get.mockResolvedValue({ data: {} });

      const unsubscribe = api.streamMetrics(onUpdate, 1000);

      // Verify initial fetch is attempted
      expect(mockAxios.get).toHaveBeenCalledWith('/telemetry/status');

      // Verify unsubscribe is a function
      expect(typeof unsubscribe).toBe('function');

      // Clean up
      unsubscribe();
    });

    it('should return unsubscribe function', () => {
      const onUpdate = jest.fn();
      mockAxios.get.mockResolvedValue({ data: {} });

      const unsubscribe = api.streamMetrics(onUpdate, 1000);
      expect(typeof unsubscribe).toBe('function');

      // Should not throw when called
      expect(() => unsubscribe()).not.toThrow();
    });
  });
});
