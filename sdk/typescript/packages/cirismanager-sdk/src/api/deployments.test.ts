import { AxiosInstance } from 'axios';
import { DeploymentsAPI } from './deployments';

describe('DeploymentsAPI', () => {
  let api: DeploymentsAPI;
  let mockAxios: jest.Mocked<AxiosInstance>;

  beforeEach(() => {
    mockAxios = {
      get: jest.fn(),
      post: jest.fn(),
    } as any;

    api = new DeploymentsAPI(mockAxios);
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
  });

  describe('getStatus', () => {
    it('should fetch deployment status', async () => {
      const mockStatus = {
        deployment_id: 'deploy-123',
        status: 'in_progress',
        phase: 'explorers',
        agents_total: 10,
        agents_updated: 3
      };

      mockAxios.get.mockResolvedValue({ data: mockStatus });

      const result = await api.getStatus();

      expect(mockAxios.get).toHaveBeenCalledWith('/updates/status');
      expect(result).toEqual(mockStatus);
    });

    it('should return null for 404', async () => {
      mockAxios.get.mockRejectedValue({
        response: { status: 404 }
      });

      const result = await api.getStatus();

      expect(result).toBeNull();
    });

    it('should throw other errors', async () => {
      mockAxios.get.mockRejectedValue(new Error('Network error'));

      await expect(api.getStatus()).rejects.toThrow('Network error');
    });
  });

  describe('getPending', () => {
    it('should fetch pending deployments', async () => {
      const mockPending = [
        {
          deployment_id: 'deploy-123',
          agent_image: 'image:v1.0.0',
          staged_at: '2024-01-01T00:00:00Z'
        }
      ];

      mockAxios.get.mockResolvedValue({ data: mockPending });

      const result = await api.getPending();

      expect(mockAxios.get).toHaveBeenCalledWith('/updates/pending');
      expect(result).toEqual(mockPending);
    });
  });

  describe('launch', () => {
    it('should launch deployment', async () => {
      const mockStatus = {
        deployment_id: 'deploy-123',
        status: 'in_progress'
      };

      mockAxios.post.mockResolvedValue({ data: mockStatus });

      const result = await api.launch('deploy-123', false);

      expect(mockAxios.post).toHaveBeenCalledWith('/updates/launch', {
        deployment_id: 'deploy-123',
        force: false
      });
      expect(result).toEqual(mockStatus);
    });

    it('should force launch when requested', async () => {
      const mockStatus = {
        deployment_id: 'deploy-123',
        status: 'in_progress'
      };

      mockAxios.post.mockResolvedValue({ data: mockStatus });

      await api.launch('deploy-123', true);

      expect(mockAxios.post).toHaveBeenCalledWith('/updates/launch', {
        deployment_id: 'deploy-123',
        force: true
      });
    });
  });

  describe('reject', () => {
    it('should reject deployment', async () => {
      const mockResponse = { message: 'Deployment rejected' };
      mockAxios.post.mockResolvedValue({ data: mockResponse });

      const result = await api.reject('deploy-123', 'Critical issue found');

      expect(mockAxios.post).toHaveBeenCalledWith('/updates/reject', {
        deployment_id: 'deploy-123',
        reason: 'Critical issue found'
      });
      expect(result).toEqual(mockResponse);
    });
  });

  describe('pause', () => {
    it('should pause deployment', async () => {
      const mockResponse = { message: 'Deployment paused' };
      mockAxios.post.mockResolvedValue({ data: mockResponse });

      const result = await api.pause();

      expect(mockAxios.post).toHaveBeenCalledWith('/updates/pause');
      expect(result).toEqual(mockResponse);
    });
  });

  describe('rollback', () => {
    it('should initiate rollback', async () => {
      const rollbackRequest = {
        target_version: 'n-1' as const,
        reason: 'Performance issues'
      };

      const mockStatus = {
        deployment_id: 'rollback-123',
        status: 'in_progress',
        is_rollback: true
      };

      mockAxios.post.mockResolvedValue({ data: mockStatus });

      const result = await api.rollback(rollbackRequest);

      expect(mockAxios.post).toHaveBeenCalledWith('/updates/rollback', rollbackRequest);
      expect(result).toEqual(mockStatus);
    });
  });

  describe('getHistory', () => {
    it('should fetch deployment history', async () => {
      const mockHistory = [
        { deployment_id: 'deploy-1', status: 'completed' },
        { deployment_id: 'deploy-2', status: 'failed' }
      ];

      mockAxios.get.mockResolvedValue({ data: mockHistory });

      const result = await api.getHistory(20);

      expect(mockAxios.get).toHaveBeenCalledWith('/updates/history', {
        params: { limit: 20 }
      });
      expect(result).toEqual(mockHistory);
    });

    it('should use default limit', async () => {
      mockAxios.get.mockResolvedValue({ data: [] });

      await api.getHistory();

      expect(mockAxios.get).toHaveBeenCalledWith('/updates/history', {
        params: { limit: 10 }
      });
    });
  });

  describe('getRollbackOptions', () => {
    it('should fetch rollback options', async () => {
      const mockOptions = {
        'n-1': { version: '1.0.0', deployment_id: 'deploy-1' },
        'n-2': { version: '0.9.0', deployment_id: 'deploy-2' }
      };

      mockAxios.get.mockResolvedValue({ data: mockOptions });

      const result = await api.getRollbackOptions();

      expect(mockAxios.get).toHaveBeenCalledWith('/updates/rollback-options');
      expect(result).toEqual(mockOptions);
    });
  });

  describe('getCurrentImages', () => {
    it('should fetch current images', async () => {
      const mockImages = {
        agents: 'agent:v1.0.0',
        gui: 'gui:v2.0.0',
        nginx: 'nginx:v1.0.0'
      };

      mockAxios.get.mockResolvedValue({ data: mockImages });

      const result = await api.getCurrentImages();

      expect(mockAxios.get).toHaveBeenCalledWith('/updates/current-images');
      expect(result).toEqual(mockImages);
    });
  });

  describe('watchDeployment', () => {
    it('should start polling deployment status', () => {
      const onUpdate = jest.fn();
      mockAxios.get.mockResolvedValue({ data: { deployment_id: 'deploy-123', status: 'in_progress' } });

      const unsubscribe = api.watchDeployment('deploy-123', onUpdate);

      // Verify polling was started
      expect(mockAxios.get).toHaveBeenCalledWith('/updates/status');

      // Verify unsubscribe is a function
      expect(typeof unsubscribe).toBe('function');

      // Clean up
      unsubscribe();
    });

    it('should return unsubscribe function', () => {
      const onUpdate = jest.fn();
      mockAxios.get.mockResolvedValue({ data: { deployment_id: 'deploy-123', status: 'in_progress' } });

      const unsubscribe = api.watchDeployment('deploy-123', onUpdate);
      expect(typeof unsubscribe).toBe('function');

      // Should not throw when called
      expect(() => unsubscribe()).not.toThrow();
    });
  });

  describe('notify', () => {
    it('should send update notification', async () => {
      const notification = {
        agent_image: 'agent:v2.0.0',
        gui_image: 'gui:v2.0.0',
        strategy: 'canary' as const,
        message: 'New features available'
      };

      const mockStatus = {
        deployment_id: 'deploy-124',
        status: 'staged'
      };

      mockAxios.post.mockResolvedValue({ data: mockStatus });

      const result = await api.notify(notification);

      expect(mockAxios.post).toHaveBeenCalledWith('/updates/notify', notification);
      expect(result).toEqual(mockStatus);
    });
  });
});
