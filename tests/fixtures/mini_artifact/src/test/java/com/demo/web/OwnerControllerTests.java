package com.demo.web;

class OwnerControllerTests {

    @Test
    void testCreateOwnerSuccess() throws Exception {
        this.mockMvc.perform(post("/api/owners")
            .content(json))
            .andExpect(status().isCreated());
    }

    @Test
    void testDeleteOwnerSuccess() throws Exception {
        this.mockMvc.perform(delete("/api/owners/1"))
            .andExpect(status().isNoContent());
    }

    @Test
    void testListOwnersByLastName() throws Exception {
        this.mockMvc.perform(get("/api/owners?lastName=Davis"))
            .andExpect(status().isOk());
    }
}
