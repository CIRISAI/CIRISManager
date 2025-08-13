/**
 * Tests for CIRIS Telemetry SDK Client
 */

import axios from 'axios';
import { CIRISTelemetryClient, createTelemetryClient } from '../src/client';
import {
  HealthResponse,
  SystemSummary,
  PublicStatus,
  TelemetryError,
  CollectionError
} from '../src/types';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

describe('CIRISTelemetryClient', () => {
  let client: CIRISTelemetryClient;
  const baseUrl = 'https://api.ciris.ai';
  const apiKey = 'test-api-key';
  
  beforeEach(() => {
    jest.clearAllMocks();
    mockedAxios.create.mockReturnValue({
      get: jest.fn(),
      post: jest.fn(),
      request: jest.fn(),
      defaults: { headers: {} },
      interceptors: {
        response: { use: jest.fn() }
      }
    } as any);
    
    client = new CIRISTelemetryClient({
      baseUrl,
      apiKey,
      timeout: 5000,
      enableCache: true
    });
  });
  
  describe('Health & Status', () => {
    test('should get health status', async () => {
      const mockHealth: HealthResponse = {
        status: 'healthy',
        collection_status: 'active',
        last_collection_time: '2025-01-01T00:00:00Z',
        database_connected: true,
        collectors_enabled: {
          docker: true,
          agents: true,
          deployments: true,
          versions: true
        },
        collection_interval: 60,
        storage_enabled: true
      };
      
      const axiosInstance = (client as any).axios;
      axiosInstance.request = jest.fn().mockResolvedValue({ data: mockHealth });
      
      const result = await client.getHealth();
      
      expect(result).toEqual(mockHealth);
      expect(axiosInstance.request).toHaveBeenCalledWith({
        method: 'GET',
        url: '/telemetry/health',
        undefined
      });
    });
    
    test('should get system status', async () => {
      const mockStatus: SystemSummary = {
        timestamp: '2025-01-01T00:00:00Z',
        agents_total: 5,
        agents_healthy: 4,
        agents_degraded: 0,
        agents_down: 1,
        agents_in_work: 2,
        agents_in_dream: 1,
        agents_in_solitude: 1,
        agents_in_play: 1,
        total_cpu_percent: 150.5,
        total_memory_mb: 2048,
        total_cost_cents_24h: 500,
        total_messages_24h: 5000,
        total_incidents_24h: 10,
        active_deployments: 0,
        staged_deployments: 1,
        agents_on_latest: 3,
        agents_on_previous: 1,
        agents_on_older: 1
      };
      
      const axiosInstance = (client as any).axios;
      axiosInstance.request = jest.fn().mockResolvedValue({ data: mockStatus });
      
      const result = await client.getStatus();
      
      expect(result).toEqual(mockStatus);
      expect(axiosInstance.request).toHaveBeenCalledTimes(1);
    });
    
    test('should cache status responses', async () => {
      const mockStatus: SystemSummary = {
        timestamp: '2025-01-01T00:00:00Z',
        agents_total: 5,
        agents_healthy: 5,
        agents_degraded: 0,
        agents_down: 0,
        agents_in_work: 5,
        agents_in_dream: 0,
        agents_in_solitude: 0,
        agents_in_play: 0,
        total_cpu_percent: 100,
        total_memory_mb: 1024,
        total_cost_cents_24h: 100,
        total_messages_24h: 1000,
        total_incidents_24h: 0,
        active_deployments: 0,
        staged_deployments: 0,
        agents_on_latest: 5,
        agents_on_previous: 0,
        agents_on_older: 0
      };
      
      const axiosInstance = (client as any).axios;
      axiosInstance.request = jest.fn().mockResolvedValue({ data: mockStatus });
      
      // First call should make request
      const result1 = await client.getStatus();
      expect(axiosInstance.request).toHaveBeenCalledTimes(1);
      
      // Second call should use cache
      const result2 = await client.getStatus();
      expect(axiosInstance.request).toHaveBeenCalledTimes(1);
      
      expect(result1).toEqual(result2);
    });
  });
  
  describe('Public API', () => {
    test('should get public status', async () => {
      const mockPublicStatus: PublicStatus = {
        timestamp: '2025-01-01T00:00:00Z',
        total_agents: 5,
        healthy_percentage: 80,
        message_volume_24h: 5000,
        incident_count_24h: 10,
        deployment_active: false
      };
      
      const axiosInstance = (client as any).axios;
      axiosInstance.request = jest.fn().mockResolvedValue({ data: mockPublicStatus });
      
      const result = await client.getPublicStatus();
      
      expect(result).toEqual(mockPublicStatus);
      expect(axiosInstance.request).toHaveBeenCalledWith({
        method: 'GET',
        url: '/telemetry/public/status',
        undefined
      });
    });
    
    test('should get public history', async () => {
      const mockHistory = [
        {
          timestamp: '2025-01-01T00:00:00Z',
          total_agents: 5,
          healthy_agents: 4,
          total_messages: 100,
          total_incidents: 1
        },
        {
          timestamp: '2025-01-01T00:05:00Z',
          total_agents: 5,
          healthy_agents: 5,
          total_messages: 150,
          total_incidents: 0
        }
      ];
      
      const axiosInstance = (client as any).axios;
      axiosInstance.request = jest.fn().mockResolvedValue({ data: mockHistory });
      
      const result = await client.getPublicHistory(24, 5);
      
      expect(result).toEqual(mockHistory);
      expect(axiosInstance.request).toHaveBeenCalledWith({
        method: 'GET',
        url: '/telemetry/public/history',
        params: { hours: 24, interval: 5 }
      });
    });
  });
  
  describe('Management', () => {
    test('should trigger collection', async () => {
      const mockResponse = {
        status: 'success',
        message: 'Collection triggered',
        collection_id: 'abc123',
        duration_ms: 150
      };
      
      const axiosInstance = (client as any).axios;
      axiosInstance.request = jest.fn().mockResolvedValue({ data: mockResponse });
      
      const result = await client.triggerCollection();
      
      expect(result).toEqual(mockResponse);
      expect(axiosInstance.request).toHaveBeenCalledWith({
        method: 'POST',
        url: '/telemetry/collect',
        undefined
      });
    });
    
    test('should clear cache after triggering collection', async () => {
      const axiosInstance = (client as any).axios;
      axiosInstance.request = jest.fn().mockResolvedValue({ 
        data: { status: 'success', message: 'OK' } 
      });
      
      // Add something to cache
      await client.getPublicStatus();
      expect((client as any).cache.size).toBeGreaterThan(0);
      
      // Trigger collection should clear cache
      await client.triggerCollection();
      expect((client as any).cache.size).toBe(0);
    });
  });
  
  describe('Error Handling', () => {
    test('should handle 503 errors as CollectionError', async () => {
      const axiosInstance = (client as any).axios;
      axiosInstance.request = jest.fn().mockRejectedValue({
        response: { 
          status: 503, 
          data: { detail: 'Service unavailable' } 
        },
        isAxiosError: true
      });
      
      await expect(client.getStatus()).rejects.toThrow(CollectionError);
    });
    
    test('should handle network errors', async () => {
      const axiosInstance = (client as any).axios;
      axiosInstance.request = jest.fn().mockRejectedValue(new Error('Network error'));
      
      await expect(client.getHealth()).rejects.toThrow('Network error');
    });
  });
  
  describe('WebSocket', () => {
    test('should connect to WebSocket', () => {
      const mockWebSocket = jest.fn();
      global.WebSocket = mockWebSocket as any;
      
      const onMessage = jest.fn();
      const onError = jest.fn();
      
      client.connectWebSocket(onMessage, onError);
      
      expect(mockWebSocket).toHaveBeenCalledWith('ws://api.ciris.ai/telemetry/ws');
    });
    
    test('should handle WebSocket reconnection', () => {
      // Test reconnection logic
      jest.useFakeTimers();
      
      const mockWebSocket = {
        readyState: WebSocket.CLOSED,
        close: jest.fn()
      };
      global.WebSocket = jest.fn().mockReturnValue(mockWebSocket) as any;
      
      const onMessage = jest.fn();
      const onError = jest.fn();
      
      client.connectWebSocket(onMessage, onError);
      
      // Simulate close event
      mockWebSocket.onclose?.();
      
      // Should attempt reconnect after delay
      jest.advanceTimersByTime(1000);
      
      expect(global.WebSocket).toHaveBeenCalledTimes(2);
      
      jest.useRealTimers();
    });
  });
});

describe('createTelemetryClient', () => {
  test('should create client with default options', () => {
    const client = createTelemetryClient('https://api.ciris.ai', 'test-key');
    
    expect(client).toBeInstanceOf(CIRISTelemetryClient);
    expect((client as any).options.baseUrl).toBe('https://api.ciris.ai');
    expect((client as any).options.apiKey).toBe('test-key');
    expect((client as any).options.enableCache).toBe(true);
  });
});