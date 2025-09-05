import { AxiosInstance } from 'axios';
import { AgentsAPI } from './agents';

describe('AgentsAPI', () => {
  let api: AgentsAPI;
  let mockAxios: jest.Mocked<AxiosInstance>;

  beforeEach(() => {
    mockAxios = {
      get: jest.fn(),
      post: jest.fn(),
      patch: jest.fn(),
      delete: jest.fn(),
    } as any;

    api = new AgentsAPI(mockAxios);
  });

  describe('list', () => {
    it('should fetch agents list', async () => {
      const mockAgents = {
        agents: [
          { agent_id: 'agent1', agent_name: 'Test Agent 1' },
          { agent_id: 'agent2', agent_name: 'Test Agent 2' }
        ]
      };

      mockAxios.get.mockResolvedValue({ data: mockAgents });

      const result = await api.list();

      expect(mockAxios.get).toHaveBeenCalledWith('/agents');
      expect(result).toEqual(mockAgents);
    });
  });

  describe('get', () => {
    it('should fetch single agent', async () => {
      const mockAgent = {
        agent_id: 'agent1',
        agent_name: 'Test Agent',
        status: 'running'
      };

      mockAxios.get.mockResolvedValue({ data: mockAgent });

      const result = await api.get('agent1');

      expect(mockAxios.get).toHaveBeenCalledWith('/agents/agent1');
      expect(result).toEqual(mockAgent);
    });
  });

  describe('create', () => {
    it('should create new agent', async () => {
      const createRequest = {
        agent_name: 'new-agent',
        template: 'default',
        memory_limit: '2G'
      };

      const mockAgent = {
        agent_id: 'new-agent',
        agent_name: 'new-agent',
        status: 'stopped'
      };

      mockAxios.post.mockResolvedValue({ data: mockAgent });

      const result = await api.create(createRequest);

      expect(mockAxios.post).toHaveBeenCalledWith('/agents', createRequest);
      expect(result).toEqual(mockAgent);
    });
  });

  describe('delete', () => {
    it('should delete agent', async () => {
      mockAxios.delete.mockResolvedValue({ data: {} });

      await api.delete('agent1');

      expect(mockAxios.delete).toHaveBeenCalledWith('/agents/agent1');
    });
  });

  describe('start', () => {
    it('should start agent', async () => {
      const mockResponse = { message: 'Agent started' };
      mockAxios.post.mockResolvedValue({ data: mockResponse });

      const result = await api.start('agent1');

      expect(mockAxios.post).toHaveBeenCalledWith('/agents/agent1/start');
      expect(result).toEqual(mockResponse);
    });
  });

  describe('stop', () => {
    it('should stop agent', async () => {
      const mockResponse = { message: 'Agent stopped' };
      mockAxios.post.mockResolvedValue({ data: mockResponse });

      const result = await api.stop('agent1');

      expect(mockAxios.post).toHaveBeenCalledWith('/agents/agent1/stop');
      expect(result).toEqual(mockResponse);
    });
  });

  describe('restart', () => {
    it('should restart agent', async () => {
      const mockResponse = { message: 'Agent restarted' };
      mockAxios.post.mockResolvedValue({ data: mockResponse });

      const result = await api.restart('agent1');

      expect(mockAxios.post).toHaveBeenCalledWith('/agents/agent1/restart');
      expect(result).toEqual(mockResponse);
    });
  });

  describe('shutdown', () => {
    it('should request graceful shutdown', async () => {
      const mockResponse = { message: 'Shutdown requested' };
      mockAxios.post.mockResolvedValue({ data: mockResponse });

      const result = await api.shutdown('agent1', false);

      expect(mockAxios.post).toHaveBeenCalledWith('/agents/agent1/shutdown', { force: false });
      expect(result).toEqual(mockResponse);
    });

    it('should force shutdown when requested', async () => {
      const mockResponse = { message: 'Force shutdown initiated' };
      mockAxios.post.mockResolvedValue({ data: mockResponse });

      const result = await api.shutdown('agent1', true);

      expect(mockAxios.post).toHaveBeenCalledWith('/agents/agent1/shutdown', { force: true });
      expect(result).toEqual(mockResponse);
    });
  });

  describe('getConfig', () => {
    it('should fetch agent configuration', async () => {
      const mockConfig = {
        environment: { KEY: 'value' },
        memory_limit: '1G',
        cpu_limit: '2.0'
      };

      mockAxios.get.mockResolvedValue({ data: mockConfig });

      const result = await api.getConfig('agent1');

      expect(mockAxios.get).toHaveBeenCalledWith('/agents/agent1/config');
      expect(result).toEqual(mockConfig);
    });
  });

  describe('updateConfig', () => {
    it('should update agent configuration', async () => {
      const configUpdate = {
        memory_limit: '2G',
        environment: { NEW_KEY: 'new_value' }
      };

      const mockResponse = { message: 'Configuration updated' };
      mockAxios.patch.mockResolvedValue({ data: mockResponse });

      const result = await api.updateConfig('agent1', configUpdate);

      expect(mockAxios.patch).toHaveBeenCalledWith('/agents/agent1/config', configUpdate);
      expect(result).toEqual(mockResponse);
    });
  });

  describe('getVersions', () => {
    it('should fetch agent versions', async () => {
      const mockVersions = {
        'agent1': '1.0.0',
        'agent2': '1.1.0'
      };

      mockAxios.get.mockResolvedValue({ data: mockVersions });

      const result = await api.getVersions();

      expect(mockAxios.get).toHaveBeenCalledWith('/agents/versions');
      expect(result).toEqual(mockVersions);
    });
  });
});
